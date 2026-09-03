from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    available_in_app = fields.Boolean(
        string='Show in Mobile App',
        default=True,
        help="On by default for every product. Untick it only to HIDE this "
             "product from the mobile app - it stays available everywhere "
             "else in Odoo. Products that are not saleable never appear in "
             "the app regardless of this setting.",
    )
