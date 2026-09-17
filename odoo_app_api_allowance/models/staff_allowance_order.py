from odoo import fields, models


class StaffAllowanceOrder(models.Model):
    _inherit = 'staff.allowance.order'

    sale_order_id = fields.Many2one('sale.order', string='App Order', readonly=True,
                                    copy=False, index='btree_not_null', ondelete='cascade')
