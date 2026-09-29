from odoo import fields, models


class PosOrder(models.Model):
    _inherit = 'pos.order'

    is_app_order = fields.Boolean(
        string='From Mobile App', copy=False, index=True, readonly=True,
        help="Set automatically on orders placed through the customer app.")
    app_payment_method = fields.Selection(
        [('wallet', 'eWallet'), ('waafi', 'WaafiPay'),
         ('account', 'Customer Account')],
        string='App Payment Method', copy=False, readonly=True)
    table_label = fields.Char(string='Table', compute='_compute_table_label')
    order_reference = fields.Char(string='Order Ref', compute='_compute_order_reference')

    def _compute_table_label(self):
        for order in self:
            label = ''
            if hasattr(order, 'table_id') and order.table_id:
                tbl = order.table_id
                label = getattr(tbl, 'table_number', None) or getattr(tbl, 'name', None) or f"Table {tbl.id}"
            order.table_label = str(label or '')

    def _compute_order_reference(self):
        for order in self:
            ref = getattr(order, 'pos_reference', False) or order.name or ''
            if not ref or ref == '/':
                ref = f"Order #{order.id}"
            order.order_reference = ref
