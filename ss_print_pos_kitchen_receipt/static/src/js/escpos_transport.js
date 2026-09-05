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

import { exportForKitchenPrinting } from "./utils";

const LOG = "[ss_kot]";

let printerCache = null;
let printerCachePosId = null;

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
}

export async function loadPrinters(pos) {
    const configId = pos?.config?.id ?? null;
    if (printerCache && printerCachePosId === configId) {
        return printerCache;
    }
    const rpc = getRpc(pos);
    if (!rpc) {
        console.error(LOG, "no ORM service available on the POS store");
        return [];
    }
    const printers = await rpc("ss.escpos.printer", "load_printers", [configId]);
    printerCache = printers || [];
    printerCachePosId = configId;
    if (printerCache.length === 0) {
        console.warn(
            LOG,
            "no network printers configured — Point of Sale > Configuration > Network Printers"
        );
    }
    return printerCache;
}

/** Collect every plausible POS-category id for a product. */
function productCategoryIds(product) {
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
function makeLineFilter(printer) {
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
    const url = printer.agent_url || rendered.agent_url;
    if (!url) {
        throw new Error(`printer ${printer.name} has no agent URL configured`);
    }
    const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            ip: rendered.ip,
            port: rendered.port,
            payload_b64: rendered.payload_b64,
        }),
    });
    if (!response.ok) {
        throw new Error(
            `agent at ${url} answered ${response.status} ${response.statusText}`
        );
    }
    const body = await response.json().catch(() => ({}));
    console.info(LOG, `sent to ${printer.name} via local agent`, body);
    return body;
}

/**
 * Print an order to every printer that has matching lines.
 *
 * Returns { attempted, succeeded, failures: [{printer, error}] } so the
 * caller can tell the cashier what actually happened.
 */
export async function printOrderToNetworkPrinters(pos, order, { changesOnly = true } = {}) {
    const result = { attempted: 0, succeeded: 0, failures: [], skipped: [] };
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

    for (const printer of printers) {
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
    if (!result || result.failures.length === 0) {
        return;
    }
    const detail = result.failures
        .map((f) => `${f.printer}: ${f.error?.message || f.error}`)
        .join("\n");
    const message = `Could not print to:\n${detail}`;
    const dialog = pos?.env?.services?.dialog;
    const notification = pos?.env?.services?.notification;
    if (notification && typeof notification.add === "function") {
        notification.add(message, { type: "danger", sticky: true });
    } else if (dialog && typeof dialog.add === "function") {
        console.error(LOG, message);
    } else {
        console.error(LOG, message);
    }
}
