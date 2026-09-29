from odoo import fields, models


class PosCategory(models.Model):
    _inherit = 'pos.category'

    available_in_app = fields.Boolean(
        string='Available in Mobile App',
        default=True,
        help="When ticked, this category appears in the mobile app catalogue and menu. "
             "Untick to hide it from the mobile app.",
    )
