from odoo import models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    def _app_product_extras(self, products):
        """Add what is left of the customer's allowance to each product.

        {"allowance": {"restricted": false}} for a product no limit covers;
        otherwise the tightest limit it counts against, so the app can show
        "2 left today" and grey the product out at 0.
        """
        extras = super()._app_product_extras(products)
        self.ensure_one()
        Rule = self.env['staff.allowance.rule'].sudo()
        for product in products:
            categories = Rule._counted_categories(self, product)
            if categories:
                tightest = min((Rule._evaluate(self, category) for category in categories),
                               key=lambda evaluation: evaluation['remaining'])
                info = {
                    'restricted': True,
                    'category': tightest['category_name'],
                    'limit': tightest['limit'],
                    'used': tightest['used'],
                    'remaining': tightest['remaining'],
                    'resets_at': tightest['resets_at'],
                }
            else:
                info = {'restricted': False}
            extras.setdefault(product.id, {})['allowance'] = info
        return extras
