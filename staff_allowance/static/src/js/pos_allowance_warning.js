/** @odoo-module **/

/*
 * Before a POS sale is validated, check the customer's daily allowances and
 * follow the rule's "At the Limit" setting:
 *
 *   Block (or tolerance used up)  -> popup, the sale is not validated
 *   Require approval / Allow      -> popup, "Sell anyway" or "Cancel"
 *
 * Patched on OrderPaymentValidation, which both the payment screen and the
 * quick payment buttons go through. What is sold is recorded on the server
 * either way. If the check itself fails (server unreachable, unexpected
 * data), the sale goes through rather than leaving the cashier stuck.
 */

import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { AlertDialog, ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import OrderPaymentValidation from "@point_of_sale/app/utils/order_payment_validation";

patch(OrderPaymentValidation.prototype, {
    async askBeforeValidation() {
        if ((await super.askBeforeValidation(...arguments)) === false) {
            return false;
        }
        return this._checkAllowance();
    },

    /** Resolves to false when the sale must not be validated. */
    async _checkAllowance() {
        let result;
        try {
            const partner = this.order.getPartner();
            const lines = this.order.lines
                .filter((line) => line.product_id && line.qty > 0)
                .map((line) => ({ product_id: line.product_id.id, qty: line.qty }));
            if (!partner || !lines.length) {
                return true;
            }
            result = await this.pos.data.call(
                "staff.allowance.rule",
                "check_pos_basket",
                [partner.id, lines]
            );
        } catch (error) {
            console.warn("Staff Allowance: basket check skipped", error);
            return true;
        }

        if (result?.blocked) {
            await new Promise((resolve) => {
                this.pos.dialog.add(
                    AlertDialog,
                    {
                        title: _t("Allowance limit reached"),
                        body: result.messages.join("\n\n"),
                    },
                    { onClose: resolve }
                );
            });
            return false;
        }

        if (result?.warnings?.length) {
            return new Promise((resolve) => {
                this.pos.dialog.add(
                    ConfirmationDialog,
                    {
                        title: _t("Over the allowance"),
                        body: result.warnings.join("\n\n"),
                        confirmLabel: _t("Sell anyway"),
                        confirm: () => resolve(true),
                        cancel: () => resolve(false),
                    },
                    { onClose: () => resolve(false) }
                );
            });
        }
        return true;
    },
});
