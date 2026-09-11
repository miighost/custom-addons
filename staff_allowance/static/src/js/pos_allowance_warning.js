/** @odoo-module **/

/*
 * Warns the cashier when the basket puts the customer over a daily allowance,
 * then lets the sale through. Recording happens server-side either way, so if
 * this file is disabled or fails, consumption and the over-limit flags are
 * still correct -- you just lose the popup.
 *
 * Every lookup below is defensive and the whole check is wrapped in try/catch,
 * so a renamed POS method degrades to "no warning" rather than a broken POS.
 */

import { patch } from "@web/core/utils/patch";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

patch(PaymentScreen.prototype, {
    async validateOrder(isForceValidate) {
        try {
            const order = this.pos.getOrder
                ? this.pos.getOrder()
                : this.pos.get_order();
            const partner =
                order && (order.getPartner ? order.getPartner() : order.get_partner());

            if (partner) {
                const rawLines =
                    order.lines ||
                    (order.getOrderlines ? order.getOrderlines() : []);
                const lines = rawLines
                    .map((line) => {
                        const product =
                            line.product_id ||
                            (line.get_product ? line.get_product() : null);
                        const qty =
                            line.qty !== undefined
                                ? line.qty
                                : line.get_quantity
                                ? line.get_quantity()
                                : 0;
                        return product ? { product_id: product.id, qty: qty } : null;
                    })
                    .filter(Boolean);

                if (lines.length) {
                    const result = await this.env.services.orm.call(
                        "staff.allowance.rule",
                        "check_pos_basket",
                        [partner.id, lines]
                    );
                    if (result && result.warnings && result.warnings.length) {
                        await new Promise((resolve) => {
                            this.env.services.dialog.add(
                                AlertDialog,
                                {
                                    title: "Allowance exceeded",
                                    body: result.warnings.join("\n"),
                                },
                                { onClose: resolve }
                            );
                        });
                    }
                }
            }
        } catch (error) {
            // Never let the allowance check stop a sale.
            console.warn("Staff Allowance: basket check skipped", error);
        }
        return super.validateOrder(...arguments);
    },
});
