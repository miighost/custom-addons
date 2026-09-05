/** @odoo-module */

import { patch } from "@web/core/utils/patch";
import { ReceiptScreen } from "@point_of_sale/app/screens/receipt_screen/receipt_screen";
import { onMounted, useState } from "@odoo/owl";
import { KitchenReceiptComponent } from "./KitchenReceiptComponent";
import { exportForKitchenPrinting } from "./utils";

patch(ReceiptScreen.prototype, {
    setup() {
        super.setup();
        this.kitchenPrintState = useState({
            printedChanges: false,
        });

        onMounted(() => {
            if (this.pos?.config?.kitchen_print_auto) {
                this.printKitchenChanges();
            }
        });
    },

    async printReceiptAndKitchen() {
        if (typeof this.doFullPrint === "function") {
            try {
                await this.doFullPrint();
            } catch (_e) {}
        }
        await this.printKitchenChanges();
    },

    async printKitchenChanges() {
        if (!this.kitchenPrintState.printedChanges && this.currentOrder) {
            if (typeof this.pos?.sendOrderInPreparation === "function") {
                try {
                    await this.pos.sendOrderInPreparation(this.currentOrder);
                } catch (_e) {}
            }
            this.kitchenPrintState.printedChanges = true;
        }
    },

    async printKitchenReceipt() {
        if (!this.currentOrder) {
            return;
        }
        this.currentOrder.kot_print_count = (this.currentOrder.kot_print_count || 0) + 1;
        const kitchenData = exportForKitchenPrinting(this.pos, this.currentOrder);
        if (this.pos?.printer && typeof this.pos.printer.print === "function") {
            try {
                await this.pos.printer.print(
                    KitchenReceiptComponent,
                    { data: kitchenData },
                    { webPrintFallback: true }
                );
            } catch (_e) {}
        }
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
            } catch (_e) {
                return false;
            }
        }
        return false;
    },
});
