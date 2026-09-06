/** @odoo-module */

/**
 * Transport layer between the POS front-end and the network printers.
 *
 * The front-end never talks to a printer directly. It asks the server for
 * the printer list, decides which lines belong to which printer, and then
 * dispatches per printer according to that printer's configured transport:
 *
 *   server_socket  -> ORM call, the Odoo server writes to port 9100.
 *   browser_agent  -> ORM call returns base64 bytes, this browser POSTs them
 *                     to the local agent on the till.
 *
 * Nothing here is wrapped in a silent catch. Every failure is logged and
 * returned to the caller, because a print that quietly does nothing is the
 * single hardest bug to chase in a live restaurant.
 */

import { reactive } from "@odoo/owl";
import { exportForKitchenPrinting } from "./utils";

const LOG = "[ss_kot]";

let printerCache = null;
let printerCachePosId = null;
let setupPromise = null;

/**
 * Reactive settings shared with the POS templates.
 *
 * Defaults are deliberately permissive: if the fetch never lands, the manual
 * button stays visible and automatic printing stays off. A missing setting
 * should degrade to "behave as before", never to "the button vanished".
 */
export const kitchenSettings = reactive({
    loaded: false,
    kitchen_print: true,
    kitchen_print_auto: false,
    kitchen_print_trigger: "on_send",
});

/** Resolve an RPC caller across the POS service shapes Odoo has used. */
function getRpc(pos) {
    if (pos?.data && typeof pos.data.call === "function") {
        return (model, method, args) => pos.data.call(model, method, args);
    }
    const orm = pos?.env?.services?.orm || pos?.orm;
    if (orm && typeof orm.call === "function") {
        return (model, method, args) => orm.call(model, method, args);
    }
    return null;
}

export function invalidatePrinterCache() {
    printerCache = null;
    printerCachePosId = null;
    setupPromise = null;
    kitchenSettings.loaded = false;
}

export async function loadPrinters(pos) {
    const setup = await loadSetup(pos);
    return setup.printers;
}

/**
 * Fetch printers and settings in one round trip, once per POS config.
 *
 * Concurrent callers share the same in-flight promise, so opening a screen
 * while a print is starting cannot fire two identical RPCs.
 */
export function loadSetup(pos) {
    const configId = pos?.config?.id ?? null;
    if (printerCache && printerCachePosId === configId) {
        return Promise.resolve({ printers: printerCache, settings: kitchenSettings });
    }
    if (setupPromise) {
        return setupPromise;
    }

    const rpc = getRpc(pos);
    if (!rpc) {
        console.error(LOG, "no ORM service available on the POS store");
        return Promise.resolve({ printers: [], settings: kitchenSettings });
    }

    setupPromise = rpc("ss.escpos.printer", "load_setup", [configId])
        .then((result) => {
            printerCache = result?.printers || [];
            printerCachePosId = configId;
            const settings = result?.settings || {};
            // Mutate in place: the templates hold a reference to this object.
            kitchenSettings.kitchen_print = settings.kitchen_print !== false;
            kitchenSettings.kitchen_print_auto = Boolean(settings.kitchen_print_auto);
            kitchenSettings.kitchen_print_trigger =
                settings.kitchen_print_trigger || "on_send";
            kitchenSettings.loaded = true;
            console.info(
                LOG,
                `setup loaded: ${printerCache.length} printer(s),`,
                { ...settings }
            );
            if (printerCache.length === 0) {
                console.warn(
                    LOG,
                    "no network printers configured — Point of Sale > Configuration > Network Printers"
                );
            }
            return { printers: printerCache, settings: kitchenSettings };
        })
        .catch((err) => {
            console.error(LOG, "could not load printing setup", err);
            setupPromise = null; // allow a later retry
            throw err;
        });

    return setupPromise;
}

/** Kick the fetch off early so the templates settle before first render. */
export function primeSetup(pos) {
    loadSetup(pos).catch(() => {});
}

/** Collect every plausible POS-category id for a product. */
export function productCategoryIds(product) {
    if (!product) {
        return [];
    }
    const raw = product.pos_categ_ids ?? product.pos_categ_id ?? product.categ_id;
    const out = [];
    const push = (v) => {
        if (typeof v === "number") {
            out.push(v);
        } else if (Array.isArray(v) && typeof v[0] === "number") {
            out.push(v[0]);
        } else if (v && typeof v.id === "number") {
            out.push(v.id);
        }
    };
    if (Array.isArray(raw)) {
        raw.forEach(push);
        // Handle the [id, "name"] pair shape, which Array.forEach above
        // would otherwise read as two separate entries.
        if (raw.length === 2 && typeof raw[0] === "number" && typeof raw[1] === "string") {
            out.length = 0;
            out.push(raw[0]);
        }
    } else {
        push(raw);
    }
    return out.filter((v) => typeof v === "number");
}

/** Build a line predicate for one printer's category routing. */
export function makeLineFilter(printer) {
    const wanted = printer.category_ids || [];
    if (wanted.length === 0) {
        return null; // no filter: this printer takes every line
    }
    const wantedSet = new Set(wanted);
    return (line) => {
        const product = line.getProduct ? line.getProduct() : line.product || {};
        return productCategoryIds(product).some((id) => wantedSet.has(id));
    };
}

/**
 * Which order lines does no printer claim?
 *
 * A line whose product sits in a category nobody routes would be filtered out
 * of every ticket and simply never cooked, with nothing on screen to say so.
 * That is the most dangerous failure this module can have, so it is detected
 * explicitly and reported by product name.
 */
export function findUnroutedLines(pos, order, printers) {
    const lines =
        (order?.getOrderlines ? order.getOrderlines() : order?.lines) || [];
    if (lines.length === 0 || !printers || printers.length === 0) {
        return [];
    }
    // A printer with no categories is a catch-all: it takes every line, so
    // nothing can be unrouted.
    if (printers.some((p) => !p.category_ids || p.category_ids.length === 0)) {
        return [];
    }
    const filters = printers.map((p) => makeLineFilter(p)).filter(Boolean);
    const orphans = [];
    for (const line of lines) {
        if (!filters.some((f) => f(line))) {
            const product = line.getProduct ? line.getProduct() : line.product || {};
            orphans.push(product.display_name || product.name || "(unnamed product)");
        }
    }
    return orphans;
}

/**
 * Probe every printer and tell the cashier if a station is down.
 *
 * Run once when the POS opens. A printer that is unplugged at 11am should be
 * discovered then, not at 8pm with a full restaurant and a queue at the till.
 */
export async function runHealthCheck(pos) {
    const rpc = getRpc(pos);
    if (!rpc) {
        return null;
    }
    const configId = pos?.config?.id ?? null;
    let report;
    try {
        report = await rpc("ss.escpos.printer", "health_check", [configId]);
    } catch (err) {
        console.error(LOG, "health check failed", err);
        return null;
    }

    console.info(LOG, "printer health check", report);
    const notification = pos?.env?.services?.notification;

    if (report.total === 0) {
        const message =
            "No printers are configured. Set them up in Point of Sale > " +
            "Configuration > Network Printers.";
        console.warn(LOG, message);
        notification?.add?.(message, { type: "warning", sticky: true });
        return report;
    }

    if (report.offline.length > 0) {
        const names = report.offline.map((p) => `${p.name} (${p.ip})`).join(", ");
        const message = `Printer not responding: ${names}\nTickets for that station will not print.`;
        console.error(LOG, message);
        notification?.add?.(message, { type: "danger", sticky: true });
    } else if (report.online.length > 0) {
        notification?.add?.(
            `All ${report.online.length} printer(s) responding.`,
            { type: "success" }
        );
    }
    return report;
}

/** Printers that receive kitchen tickets. The bill printer is not one. */
export function kitchenPrinters(printers) {
    return (printers || []).filter((p) => (p.role || "kitchen") === "kitchen");
}

/** The printer that prints customer bills, if one is configured. */
export function receiptPrinter(printers) {
    return (printers || []).find((p) => p.role === "receipt") || null;
}

/**
 * Hand a rendered job to the local agent.
 *
 * The job describes its own target: an ip/port for a network printer, or a
 * printer_name for one plugged into the till by USB. The agent decides how to
 * reach it, so nothing here needs to know the difference.
 */
export async function deliverViaAgent(job, agentUrlHint) {
    const url = job.agent_url || agentUrlHint;
    if (!url) {
        throw new Error(`printer ${job.name} has no agent URL configured`);
    }
    const body =
        job.connection === "local"
            ? { printer_name: job.printer_name, payload_b64: job.payload_b64 }
            : { ip: job.ip, port: job.port, payload_b64: job.payload_b64 };

    let response;
    try {
        response = await fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });
    } catch (err) {
        throw new Error(
            `local print agent not reachable at ${url} — is it running on this till? (${err.message})`
        );
    }
    if (!response.ok) {
        let detail = `${response.status} ${response.statusText}`;
        try {
            const payload = await response.json();
            if (payload?.error) {
                detail = payload.error;
            }
        } catch (_e) {
            // keep the status line
        }
        throw new Error(`agent refused the job: ${detail}`);
    }
    return response.json().catch(() => ({}));
}

/** Send one already-built ticket payload to one printer. */
async function dispatchToPrinter(pos, printer, data) {
    const rpc = getRpc(pos);
    if (!rpc) {
        throw new Error("no ORM service available");
    }

    if (printer.transport === "server_socket") {
        const res = await rpc("ss.escpos.printer", "print_ticket", [printer.id, data]);
        console.info(LOG, `sent to ${printer.name} via server socket`, res);
        return res;
    }

    // browser_agent: the server renders, this browser delivers.
    const rendered = await rpc("ss.escpos.printer", "render_ticket", [printer.id, data]);
    const body = await deliverViaAgent(rendered, printer.agent_url);
    console.info(LOG, `sent to ${printer.name} via local agent`, body);
    return body;
}

/**
 * Print the customer bill for a saved order.
 *
 * The server renders from the persisted pos.order, so the printed bill always
 * matches what was actually recorded rather than the browser's in-memory copy.
 */
export async function printCustomerBill(pos, orderId) {
    if (!orderId) {
        console.warn(LOG, "no saved order id yet; skipping bill print");
        return { ok: false, error: "no_order_id" };
    }
    const rpc = getRpc(pos);
    if (!rpc) {
        throw new Error("no ORM service available");
    }
    const { printers } = await loadSetup(pos);
    const printer = receiptPrinter(printers);
    if (!printer) {
        console.info(LOG, "no bill printer configured; leaving the receipt to Odoo");
        return { ok: false, error: "no_receipt_printer" };
    }
    const configId = pos?.config?.id ?? null;

    if (printer.transport === "server_socket") {
        const res = await rpc("ss.escpos.printer", "print_bill", [orderId, configId]);
        console.info(LOG, "bill printed via server socket", res);
        return res;
    }

    const job = await rpc("ss.escpos.printer", "render_bill_job", [orderId, configId]);
    if (!job || job.ok === false) {
        throw new Error(`could not render the bill: ${job?.error || "unknown"}`);
    }
    const body = await deliverViaAgent(job, printer.agent_url);
    console.info(LOG, "bill printed via local agent", body);
    return body;
}

/**
 * Print an order to every printer that has matching lines.
 *
 * Returns { attempted, succeeded, failures: [{printer, error}] } so the
 * caller can tell the cashier what actually happened.
 */
export async function printOrderToNetworkPrinters(pos, order, { changesOnly = true } = {}) {
    const result = { attempted: 0, succeeded: 0, failures: [], skipped: [], unrouted: [] };
    if (!pos || !order) {
        console.error(LOG, "printOrderToNetworkPrinters called without pos or order");
        return result;
    }

    let printers;
    try {
        printers = await loadPrinters(pos);
    } catch (err) {
        console.error(LOG, "could not load printer list", err);
        result.failures.push({ printer: "(printer list)", error: err });
        return result;
    }

    const unrouted = findUnroutedLines(pos, order, kitchenPrinters(printers));
    if (unrouted.length > 0) {
        console.error(
            LOG,
            "these lines match no printer's categories and will NOT be cooked:",
            unrouted
        );
        result.unrouted = unrouted;
    }

    for (const printer of kitchenPrinters(printers)) {
        const filter = makeLineFilter(printer);
        const data = exportForKitchenPrinting(pos, order, filter);
        if (!data || !data.orderlines || data.orderlines.length === 0) {
            result.skipped.push(printer.name);
            continue;
        }
        // On a re-fire, only send to stations that actually have changes.
        if (changesOnly && order.was_kot_printed && !data.has_new_items) {
            result.skipped.push(printer.name);
            continue;
        }
        result.attempted += 1;
        try {
            await dispatchToPrinter(pos, printer, data);
            result.succeeded += 1;
        } catch (err) {
            console.error(LOG, `print to "${printer.name}" failed:`, err);
            result.failures.push({ printer: printer.name, error: err });
        }
    }

    if (result.attempted === 0 && result.skipped.length > 0) {
        console.info(LOG, "nothing to print; all stations skipped", result.skipped);
    }
    return result;
}

/** Show the cashier a dialog when a station did not print. */
export function reportPrintFailures(pos, result) {
    if (!result) {
        return;
    }
    const notification = pos?.env?.services?.notification;

    // Unrouted lines are a configuration fault, not a printer fault, and the
    // consequence is a dish that never gets made. Say so separately and loudly.
    if (result.unrouted && result.unrouted.length > 0) {
        const names = [...new Set(result.unrouted)].join(", ");
        const warning =
            `Not sent to any printer: ${names}\n` +
            `Add their POS category to a printer, or leave one printer's ` +
            `categories empty so it takes everything.`;
        if (notification && typeof notification.add === "function") {
            notification.add(warning, { type: "warning", sticky: true });
        }
        console.error(LOG, warning);
    }

    if (result.failures.length === 0) {
        return;
    }
    const detail = result.failures
        .map((f) => `${f.printer}: ${f.error?.message || f.error}`)
        .join("\n");
    const message = `Could not print to:\n${detail}`;
    const dialog = pos?.env?.services?.dialog;
    if (notification && typeof notification.add === "function") {
        notification.add(message, { type: "danger", sticky: true });
    } else if (dialog && typeof dialog.add === "function") {
        console.error(LOG, message);
    } else {
        console.error(LOG, message);
    }
}
