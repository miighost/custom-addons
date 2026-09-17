from odoo import _, fields, models

from ..api_error import ApiError


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
        [('wallet', 'eWallet'), ('waafi', 'WaafiPay'),
         ('account', 'Customer Account')],
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

    def _app_confirm_and_invoice(self):
        """Confirm the order and post its invoice; returns the invoice.

        Every paid or pay-later app order is invoiced straight away, so the
        customer's Balance page and the accounting agree from the start.
        """
        self.ensure_one()
        delivery_based = self.order_line.filtered(
            lambda line: not line.display_type
            and line.product_id.invoice_policy == 'delivery')
        if delivery_based:
            raise ApiError(
                'not_invoiceable', products=delivery_based.product_id.mapped('display_name'),
                message=_("These products are invoiced on delivered quantities, so the "
                          "order cannot be invoiced yet. In Odoo, set their Invoicing "
                          "Policy to Ordered quantities."))
        if self.state in ('draft', 'sent'):
            self.action_confirm()
        invoice = self.invoice_ids.filtered(lambda move: move.state != 'cancel')[:1]
        if not invoice:
            invoice = self._create_invoices()
        if invoice.state == 'draft':
            invoice.action_post()
        return invoice

    def _app_check_allowance(self):
        """Whether the customer's allowances let this order through.

        {"blocked": bool, "messages": [...], "warnings": [...]}. Nothing to
        check here; the App API: Staff Allowance module fills it in when Staff
        Allowance is installed.
        """
        return {'blocked': False, 'messages': [], 'warnings': []}
