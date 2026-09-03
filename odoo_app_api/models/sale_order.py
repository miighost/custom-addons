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
