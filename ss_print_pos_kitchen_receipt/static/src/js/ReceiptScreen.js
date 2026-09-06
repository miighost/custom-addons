/** @odoo-module */

import { patch } from "@web/core/utils/patch";
import { ReceiptScreen } from "@point_of_sale/app/screens/receipt_screen/receipt_screen";
import { onMounted, useState } from "@odoo/owl";
import { exportForKitchenPrinting } from "./utils";
import {
    printOrderToNetworkPrinters,
    reportPrintFailures,
    kitchenSettings,
    printCustomerBill,
} from "./escpos_transport";
import { shouldAutoPrint, TRIGGER_ON_PAYMENT } from "./trigger_rules";

const LOG = "[ss_kot]";

patch(ReceiptScreen.prototype, {
    setup() {
        super.setup();
        this.kitchenPrintState = useState({
            printedChanges: false,
            printedBill: false,
        });

        onMounted(() => {
            // Only when the shop is configured to print at payment. With the
            // on_send trigger the ticket already went to the kitchen when the
            // waiter left the order screen, and firing again here would
            // duplicate it.
            const order = this.currentOrder;
            const fire = shouldAutoPrint({
                moment: TRIGGER_ON_PAYMENT,
                settings: kitchenSettings,
                hasLines: Boolean(order),
                hasUnsentChanges: true,
            });
            if (!fire) {
                return;
            }
            // Fire and forget, but never silently: an unhandled rejection
            // here is what "automatic printing does nothing" looks like.
            this.printKitchenChanges().catch((err) =>
                console.error(LOG, "automatic kitchen print failed", err)
            );
        });

        onMounted(() => {
            // The customer bill goes to the receipt printer as soon as the
            // receipt screen opens. No-ops when no bill printer is configured.
            this.printCustomerBillOnce().catch((err) =>
                console.error(LOG, "automatic bill print failed", err)
            );
        });
    },

    async printReceiptAndKitchen() {
        if (typeof this.doFullPrint === "function") {
            try {
                await this.doFullPrint();
            } catch (err) {
                console.error(LOG, "customer receipt print failed", err);
            }
        }
        await this.printKitchenChanges();
    },

    async printKitchenChanges() {
        if (this.kitchenPrintState.printedChanges || !this.currentOrder) {
            return null;
        }

        if (typeof this.pos?.sendOrderInPreparation === "function") {
            try {
                await this.pos.sendOrderInPreparation(this.currentOrder);
            } catch (err) {
                console.warn(LOG, "native sendOrderInPreparation failed", err);
            }
        }

        const result = await printOrderToNetworkPrinters(
            this.pos,
            this.currentOrder,
            { changesOnly: true }
        );
        reportPrintFailures(this.pos, result);

        // Only latch when something actually printed, otherwise a transient
        // network failure would permanently suppress the ticket.
        if (result.succeeded > 0 || result.attempted === 0) {
            this.kitchenPrintState.printedChanges = true;
        }
        return result;
    },

    async printKitchenReceipt() {
        if (!this.currentOrder) {
            return null;
        }
        this.currentOrder.kot_print_count =
            (this.currentOrder.kot_print_count || 0) + 1;
        const result = await printOrderToNetworkPrinters(
            this.pos,
            this.currentOrder,
            { changesOnly: false }
        );
        reportPrintFailures(this.pos, result);
        return result;
    },

    /** The server-side id of the order, once it has been saved. */
    _savedOrderId() {
        const order = this.currentOrder;
        if (!order) {
            return null;
        }
        for (const key of ["id", "server_id", "backendId"]) {
            const value = order[key];
            if (typeof value === "number" && value > 0) {
                return value;
            }
        }
        return null;
    },

    /** Print the bill exactly once per visit to this screen. */
    async printCustomerBillOnce() {
        if (this.kitchenPrintState.printedBill) {
            return null;
        }
        const orderId = this._savedOrderId();
        if (!orderId) {
            console.warn(LOG, "order has no saved id yet; bill not printed");
            return null;
        }
        // Latch before awaiting so a second mount cannot race in.
        this.kitchenPrintState.printedBill = true;
        try {
            return await printCustomerBill(this.pos, orderId);
        } catch (err) {
            // Unlatch: a failed attempt should be retryable from the button.
            this.kitchenPrintState.printedBill = false;
            const notification = this.pos?.env?.services?.notification;
            if (notification?.add) {
                notification.add(`Bill did not print: ${err.message}`, {
                    type: "danger",
                    sticky: true,
                });
            }
            throw err;
        }
    },

    /** Manual reprint of the customer bill. */
    async printCustomerBillAgain() {
        this.kitchenPrintState.printedBill = false;
        return this.printCustomerBillOnce();
    },

    _exportForKitchenPrinting(order) {
        return exportForKitchenPrinting(this.pos, order || this.currentOrder);
    },

    hasKitchenChanges() {
        if (!this.currentOrder || !this.pos) {
            return false;
        }
        if (typeof this.pos.getOrderChanges === "function") {
            try {
                const changes = this.pos.getOrderChanges(this.currentOrder);
                return Boolean(
                    changes?.nbrOfChanges ||
                        (changes?.noteUpdate && Object.keys(changes.noteUpdate).length) ||
                        changes?.general_customer_note ||
                        changes?.internal_note
                );
            } catch (err) {
                console.warn(LOG, "getOrderChanges failed", err);
                return false;
            }
        }
        return false;
    },
});
