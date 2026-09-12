from odoo import fields, models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    is_app_order = fields.Boolean(
        string='From Mobile App', copy=False, index=True, readonly=True,
        help="Set automatically on orders placed through the customer app.")
    app_payment_reference = fields.Char(
        string='App Payment Reference', copy=False, readonly=True,
        help="Transaction id returned by the payment gateway for an order "
             "paid from the mobile app.")
    app_payment_method = fields.Selection(
        [('wallet', 'eWallet'), ('waafi', 'WaafiPay')],
        string='App Payment Method', copy=False, readonly=True)

    def _app_apply_wallet(self, cards):
        """Spend the eWallet `cards` on this quotation.

        Odoo refuses eWallet codes in `_try_apply_code`: an eWallet is
        nominative and is picked up from the order's customer instead. That
        lookup only matches the exact customer on the order, while the app
        keeps wallets on the commercial partner, so the cards are attached
        explicitly. Points leave the cards when the order is confirmed.
        """
        self.ensure_one()
        self.applied_coupon_ids |= cards
        self._update_programs_and_rewards()
        claimable = self._get_claimable_rewards(forced_coupons=cards)
        for coupon, rewards in claimable.items():
            for reward in rewards.filtered(
                    lambda r: r.program_id.program_type == 'ewallet'):
                self._apply_program_reward(reward, coupon)
        self._update_programs_and_rewards()
