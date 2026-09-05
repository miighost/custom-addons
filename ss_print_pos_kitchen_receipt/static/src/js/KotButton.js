/** @odoo-module */

import { patch } from "@web/core/utils/patch";
import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { ActionpadWidget } from "@point_of_sale/app/screens/product_screen/action_pad/action_pad";
import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { exportForKitchenPrinting } from "./utils";
import {
    printOrderToNetworkPrinters,
    reportPrintFailures,
} from "./escpos_transport";

const LOG = "[ss_kot]";

function getOrderLines(order) {
    if (!order) {
        return [];
    }
    if (typeof order.get_orderlines === "function") {
        return order.get_orderlines() || [];
    }
    if (typeof order.get_order_lines === "function") {
        return order.get_order_lines() || [];
    }
    if (typeof order.getOrderlines === "function") {
        return order.getOrderlines() || [];
    }
    return order.lines || order.orderlines || [];
}

function lineQty(line) {
    if (typeof line.get_quantity === "function") {
        return line.get_quantity();
    }
    return line.quantity || line.qty || 1;
}

/** Record what has now been sent, so a re-fire only reprints the delta. */
function markLinesPrinted(order) {
    for (const line of getOrderLines(order)) {
        const qty = lineQty(line);
        line.printed_qty = qty;
        line.saved_printed_qty = qty;
        line.was_printed = true;
    }
    order.was_kot_printed = true;
}

/**
 * Send the order to every configured network printer.
 *
 * This replaces the previous implementation, which called
 * pos.printer.print(). That is the *receipt* printer service — a single
 * default device — so it could never reach two stations, and with no
 * ePOS/IoT printer configured it silently fell through to window.print().
 */
async function doPrintKitchenReceipt(posStore, currentOrder) {
    const pos = posStore || (currentOrder && currentOrder.pos);
    if (!pos) {
        console.error(LOG, "doPrintKitchenReceipt: no POS store");
        return null;
    }
    const order =
        currentOrder ||
        (typeof pos.get_order === "function" ? pos.get_order() : false) ||
        pos.selectedOrder;
    if (!order) {
        console.error(LOG, "doPrintKitchenReceipt: no order");
        return null;
    }

    const lines = getOrderLines(order);
    if (lines.length === 0 && !order.was_kot_printed) {
        console.info(LOG, "nothing to print: empty order");
        return null;
    }

    order.kot_print_count = (order.kot_print_count || 0) + 1;

    // Keep Odoo's own preparation-display / order-printer flow in step.
    // Failures here are logged rather than swallowed, but they do not stop
    // our own printing.
    if (typeof pos.sendOrderInPreparation === "function") {
        try {
            await pos.sendOrderInPreparation(order);
        } catch (err) {
            console.warn(LOG, "native sendOrderInPreparation failed", err);
        }
    }

    const result = await printOrderToNetworkPrinters(pos, order, {
        changesOnly: true,
    });

    if (result.succeeded > 0) {
        markLinesPrinted(order);
    } else if (result.attempted > 0) {
        // Nothing reached a printer: roll the counter back so the next
        // attempt is not labelled "2nd Print (Re-Order)".
        order.kot_print_count = Math.max(0, (order.kot_print_count || 1) - 1);
    }

    reportPrintFailures(pos, result);
    return result;
}

/** Manual "Print KOT" button: always reprint everything, changes or not. */
async function doManualKotPrint(posStore, currentOrder) {
    const pos = posStore;
    if (!pos) {
        console.error(LOG, "doManualKotPrint: no POS store");
        return null;
    }
    const order =
        currentOrder ||
        (typeof pos.get_order === "function" ? pos.get_order() : false) ||
        pos.selectedOrder;
    if (!order) {
        console.error(LOG, "doManualKotPrint: no order");
        return null;
    }
    if (getOrderLines(order).length === 0) {
        console.info(LOG, "manual print ignored: empty order");
        return null;
    }

    order.kot_print_count = (order.kot_print_count || 0) + 1;
    const result = await printOrderToNetworkPrinters(pos, order, {
        changesOnly: false,
    });
    reportPrintFailures(pos, result);
    return result;
}

const commonMethods = {
    _kotPos() {
        return this.pos || this.env?.services?.pos;
    },

    _kotOrder() {
        const pos = this._kotPos();
        return (
            this.currentOrder ||
            this.props?.order ||
            (pos && typeof pos.get_order === "function" ? pos.get_order() : false) ||
            pos?.selectedOrder
        );
    },

    async printKitchenReceipt() {
        return doPrintKitchenReceipt(this._kotPos(), this._kotOrder());
    },

    async onClickOrderButton() {
        await doPrintKitchenReceipt(this._kotPos(), this._kotOrder());
        if (typeof this.render === "function") {
            this.render();
        }
    },

    async sendOrderAndReturnToTables() {
        await doPrintKitchenReceipt(this._kotPos(), this._kotOrder());
        if (typeof this.render === "function") {
            this.render();
        }
    },

    async onClickManualKotButton() {
        await doManualKotPrint(this._kotPos(), this._kotOrder());
    },
};

patch(ProductScreen.prototype, {
    setup() {
        super.setup();
        const pos = this.pos || this.env?.services?.pos;
        if (pos) {
            pos.printKitchenReceipt = (order) =>
                doPrintKitchenReceipt(pos, order || this._kotOrder());
            pos.sendOrderAndReturnToTables = (order) =>
                doPrintKitchenReceipt(pos, order || this._kotOrder());
            pos.forceBrowserPrintDialog = (order) =>
                doManualKotPrint(pos, order || this._kotOrder());
        }
    },
    ...commonMethods,
});

if (ActionpadWidget && ActionpadWidget.prototype) {
    patch(ActionpadWidget.prototype, {
        get hasOrderItems() {
            return getOrderLines(this._kotOrder()).length > 0;
        },

        get hasChangesToOrder() {
            const order = this._kotOrder();
            if (!order) {
                return false;
            }
            if (getOrderLines(order).length === 0) {
                return false;
            }
            if (!order.was_kot_printed) {
                return true;
            }
            const diff = exportForKitchenPrinting(this._kotPos(), order);
            if (!diff) {
                return false;
            }
            return (
                (diff.new_lines || []).length > 0 ||
                (diff.cancelled_lines || []).length > 0
            );
        },

        get changeSummary() {
            const order = this._kotOrder();
            if (!order) {
                return null;
            }
            const diff = exportForKitchenPrinting(this._kotPos(), order);
            if (!diff) {
                return null;
            }
            const added = (diff.new_lines || []).reduce(
                (a, l) => a + (l.qty_num || 0), 0
            );
            const removed = (diff.cancelled_lines || []).reduce(
                (a, l) => a + (l.qty_num || 0), 0
            );
            const parts = [];
            if (added > 0) {
                parts.push(`+${added}`);
            }
            if (removed > 0) {
                parts.push(`-${removed}`);
            }
            return parts.length > 0 ? parts.join(" / ") : null;
        },
        ...commonMethods,
    });
}

if (ControlButtons && ControlButtons.prototype) {
    patch(ControlButtons.prototype, commonMethods);
}
