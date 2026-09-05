/** @odoo-module */

import { patch } from "@web/core/utils/patch";
import { ReceiptScreen } from "@point_of_sale/app/screens/receipt_screen/receipt_screen";
import { onMounted, useState } from "@odoo/owl";
import { exportForKitchenPrinting } from "./utils";
import {
    printOrderToNetworkPrinters,
    reportPrintFailures,
} from "./escpos_transport";

const LOG = "[ss_kot]";

patch(ReceiptScreen.prototype, {
    setup() {
        super.setup();
        this.kitchenPrintState = useState({ printedChanges: false });

        onMounted(() => {
            if (this.pos?.config?.kitchen_print_auto) {
                // Fire and forget, but never silently: an unhandled rejection
                // here is what "automatic printing does nothing" looks like.
                this.printKitchenChanges().catch((err) =>
                    console.error(LOG, "automatic kitchen print failed", err)
                );
            }
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
