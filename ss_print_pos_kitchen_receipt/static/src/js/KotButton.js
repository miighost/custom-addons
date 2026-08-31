/** @odoo-module */

import { patch } from "@web/core/utils/patch";
import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { ActionpadWidget } from "@point_of_sale/app/screens/product_screen/action_pad/action_pad";
import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { KitchenReceiptComponent } from "./KitchenReceiptComponent";
import { exportForKitchenPrinting } from "./utils";

function getOrderLines(order) {
    if (!order) return [];
    if (typeof order.get_orderlines === "function") return order.get_orderlines() || [];
    if (typeof order.get_order_lines === "function") return order.get_order_lines() || [];
    if (typeof order.getOrderlines === "function") return order.getOrderlines() || [];
    return order.lines || order.orderlines || [];
}

async function doPrintKitchenReceipt(posStore, currentOrder) {
    const pos = posStore || (currentOrder && currentOrder.pos);
    if (!pos) return;
    const order = currentOrder || (pos.get_order ? pos.get_order() : false) || pos.selectedOrder;
    if (!order) return;

    const lines = getOrderLines(order);
    if (lines.length === 0 && !order.was_kot_printed) return;

    // Increment KOT print counter on order
    order.kot_print_count = (order.kot_print_count || 0) + 1;

    // 1. Notify & send order to native preparation printers (jiko, Baar, Bar2)
    if (pos.sendOrderInPreparation) {
        try {
            await pos.sendOrderInPreparation(order);
        } catch (_e) {}
    }

    const categoriesToPrint = [];
    const foodData = exportForKitchenPrinting(pos, order, "Food");
    if (foodData && (foodData.has_new_items || !order.was_kot_printed) && foodData.orderlines.length > 0) {
        categoriesToPrint.push({ title: "KITCHEN", data: foodData });
    }

    const drinksData = exportForKitchenPrinting(pos, order, "Drinks");
    if (drinksData && (drinksData.has_new_items || !order.was_kot_printed) && drinksData.orderlines.length > 0) {
        categoriesToPrint.push({ title: "BAR", data: drinksData });
    }

    if (categoriesToPrint.length === 0) {
        const fullData = exportForKitchenPrinting(pos, order);
        if (fullData && (fullData.has_new_items || !order.was_kot_printed) && fullData.orderlines.length > 0) {
            categoriesToPrint.push({ title: "KITCHEN", data: fullData });
        }
    }

    // 2. Local/Web POS Driver Dispatch if available
    let printed = false;
    if (categoriesToPrint.length > 0) {
        if (pos.printer && typeof pos.printer.print === "function") {
            try {
                const res = await pos.printer.print(
                    KitchenReceiptComponent,
                    { tickets: categoriesToPrint, data: categoriesToPrint[0].data },
                    { webPrintFallback: true }
                );
                printed = Boolean(res);
            } catch (_e) {}
        }

        if (!printed && pos.hardware_proxy && pos.hardware_proxy.printer) {
            try {
                await pos.hardware_proxy.printer.print_receipt(
                    KitchenReceiptComponent,
                    { data: categoriesToPrint[0].data }
                );
                printed = true;
            } catch (_e) {}
        }
    }

    // 3. Mark lines as printed so green Order button hides until new items added
    for (const line of lines) {
        const qtyNum = line.get_quantity ? line.get_quantity() : (line.quantity || line.qty || 1);
        line.printed_qty = qtyNum;
        line.saved_printed_qty = qtyNum;
        line.was_printed = true;
    }
    order.was_kot_printed = true;
}

async function doSendOrderToKitchenAndReturnToTables(posStore, currentOrder) {
    const pos = posStore;
    if (!pos) return;
    const order = currentOrder || (pos.get_order ? pos.get_order() : false) || pos.selectedOrder;
    if (!order) return;

    try {
        await doPrintKitchenReceipt(pos, order);
    } catch (_e) {}
}

async function doForceBrowserPrintDialog(posStore, currentOrder) {
    const pos = posStore;
    if (!pos) return;
    const order = currentOrder || (pos.get_order ? pos.get_order() : false) || pos.selectedOrder;
    if (!order) return;

    const categoriesToPrint = [];
    const foodData = exportForKitchenPrinting(pos, order, "Food");
    if (foodData && foodData.orderlines && foodData.orderlines.length > 0) {
        categoriesToPrint.push({ title: "KITCHEN", data: foodData });
    }

    const drinksData = exportForKitchenPrinting(pos, order, "Drinks");
    if (drinksData && drinksData.orderlines && drinksData.orderlines.length > 0) {
        categoriesToPrint.push({ title: "BAR", data: drinksData });
    }

    if (categoriesToPrint.length === 0) {
        const fullData = exportForKitchenPrinting(pos, order);
        if (fullData && fullData.orderlines && fullData.orderlines.length > 0) {
            categoriesToPrint.push({ title: "KITCHEN", data: fullData });
        }
    }

    if (categoriesToPrint.length === 0) return;

    if (pos.printer && typeof pos.printer.print === "function") {
        try {
            await pos.printer.print(
                KitchenReceiptComponent,
                { tickets: categoriesToPrint, data: categoriesToPrint[0].data },
                { webPrintFallback: true }
            );
        } catch (_e) {}
    }
}

const commonMethods = {
    async printKitchenReceipt() {
        const pos = this.pos || (this.env && this.env.services && this.env.services.pos);
        const order = this.currentOrder || (this.props && this.props.order) || (pos && pos.get_order && pos.get_order()) || (pos && pos.selectedOrder);
        await doPrintKitchenReceipt(pos, order);
    },

    async onClickOrderButton() {
        const pos = this.pos || (this.env && this.env.services && this.env.services.pos);
        const order = this.currentOrder || (this.props && this.props.order) || (pos && pos.get_order && pos.get_order()) || (pos && pos.selectedOrder);
        await doSendOrderToKitchenAndReturnToTables(pos, order);
        if (typeof this.render === "function") {
            this.render();
        }
    },

    async sendOrderAndReturnToTables() {
        const pos = this.pos || (this.env && this.env.services && this.env.services.pos);
        const order = this.currentOrder || (this.props && this.props.order) || (pos && pos.get_order && pos.get_order()) || (pos && pos.selectedOrder);
        await doSendOrderToKitchenAndReturnToTables(pos, order);
        if (typeof this.render === "function") {
            this.render();
        }
    },

    async onClickManualKotButton() {
        const pos = this.pos || (this.env && this.env.services && this.env.services.pos);
        const order = this.currentOrder || (this.props && this.props.order) || (pos && pos.get_order && pos.get_order()) || (pos && pos.selectedOrder);
        await doForceBrowserPrintDialog(pos, order);
    },
};

patch(ProductScreen.prototype, {
    setup() {
        super.setup();
        const pos = this.pos || (this.env && this.env.services && this.env.services.pos);
        if (pos) {
            pos.printKitchenReceipt = (order) =>
                doPrintKitchenReceipt(pos, order || this.currentOrder || (pos.get_order && pos.get_order()) || pos.selectedOrder);
            pos.sendOrderAndReturnToTables = (order) =>
                doSendOrderToKitchenAndReturnToTables(pos, order || this.currentOrder || (pos.get_order && pos.get_order()) || pos.selectedOrder);
            pos.forceBrowserPrintDialog = (order) =>
                doForceBrowserPrintDialog(pos, order || this.currentOrder || (pos.get_order && pos.get_order()) || pos.selectedOrder);
        }
    },
    ...commonMethods,
});

if (ActionpadWidget && ActionpadWidget.prototype) {
    patch(ActionpadWidget.prototype, {
        get hasOrderItems() {
            const pos = this.pos || (this.env && this.env.services && this.env.services.pos);
            const order = this.currentOrder || (this.props && this.props.order) || (pos && pos.get_order && pos.get_order()) || (pos && pos.selectedOrder);
            if (!order) return false;
            const lines = getOrderLines(order);
            return lines && lines.length > 0;
        },

        get hasChangesToOrder() {
            const pos = this.pos || (this.env && this.env.services && this.env.services.pos);
            const order = this.currentOrder || (this.props && this.props.order) || (pos && pos.get_order && pos.get_order()) || (pos && pos.selectedOrder);
            if (!order) return false;
            const lines = getOrderLines(order);
            if (!lines || lines.length === 0) return false;

            // If order has never been printed to KOT before, and has lines, changes exist!
            if (!order.was_kot_printed) {
                return true;
            }

            const food = exportForKitchenPrinting(pos, order, "Food");
            const drinks = exportForKitchenPrinting(pos, order, "Drinks");
            const full = exportForKitchenPrinting(pos, order);

            const newFood = (food && food.new_lines) ? food.new_lines.length : 0;
            const cancFood = (food && food.cancelled_lines) ? food.cancelled_lines.length : 0;
            const newDrinks = (drinks && drinks.new_lines) ? drinks.new_lines.length : 0;
            const cancDrinks = (drinks && drinks.cancelled_lines) ? drinks.cancelled_lines.length : 0;
            const newFull = (full && full.new_lines) ? full.new_lines.length : 0;
            const cancFull = (full && full.cancelled_lines) ? full.cancelled_lines.length : 0;

            return (newFood > 0 || cancFood > 0 || newDrinks > 0 || cancDrinks > 0 || newFull > 0 || cancFull > 0);
        },

        get changeSummary() {
            const pos = this.pos || (this.env && this.env.services && this.env.services.pos);
            const order = this.currentOrder || (this.props && this.props.order) || (pos && pos.get_order && pos.get_order()) || (pos && pos.selectedOrder);
            if (!order) return null;
            const food = exportForKitchenPrinting(pos, order, "Food");
            const drinks = exportForKitchenPrinting(pos, order, "Drinks");

            const newFood = (food && food.new_lines) ? food.new_lines.reduce((a, l) => a + (l.qty_num || 0), 0) : 0;
            const cancFood = (food && food.cancelled_lines) ? food.cancelled_lines.reduce((a, l) => a + (l.qty_num || 0), 0) : 0;
            const newDrinks = (drinks && drinks.new_lines) ? drinks.new_lines.reduce((a, l) => a + (l.qty_num || 0), 0) : 0;
            const cancDrinks = (drinks && drinks.cancelled_lines) ? drinks.cancelled_lines.reduce((a, l) => a + (l.qty_num || 0), 0) : 0;

            const parts = [];
            if (newFood > 0) parts.push(`Food +${newFood}`);
            else if (cancFood > 0) parts.push(`Food -${cancFood}`);

            if (newDrinks > 0) parts.push(`Drinks +${newDrinks}`);
            else if (cancDrinks > 0) parts.push(`Drinks -${cancDrinks}`);

            return parts.length > 0 ? parts.join(" | ") : null;
        },
        ...commonMethods,
    });
}

if (ControlButtons && ControlButtons.prototype) {
    patch(ControlButtons.prototype, commonMethods);
}
