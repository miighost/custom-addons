from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    available_in_app = fields.Boolean(
        string='Available in App',
        default=True,
        help="Untick to hide this product from the mobile app catalogue. "
             "Products that are not saleable are hidden regardless.",
    )
