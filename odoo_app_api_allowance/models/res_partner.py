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
        eval_cache = {}
        for product in products:
            categories = Rule._counted_categories(self, product)
            if categories:
                evaluations = []
                for cat in categories:
                    if cat.id not in eval_cache:
                        eval_cache[cat.id] = Rule._evaluate(self, cat)
                    evaluations.append(eval_cache[cat.id])
                tightest = min(evaluations, key=lambda evaluation: evaluation['remaining'])
                info = {
                    'restricted': True,
                    'category': tightest['category_name'],
                    'limit': tightest['limit'],
                    'used': tightest['used'],
                    'remaining': tightest['remaining'],
                    'resets_at': tightest['resets_at'],
                }
            else:
                info = {
                    'restricted': False,
                    'category': '',
                    'limit': 0,
                    'used': 0,
                    'remaining': None,
                    'resets_at': '',
                }
            extras.setdefault(product.id, {})['allowance'] = info
        return extras

    def _app_me_extras(self):
        extras = super()._app_me_extras()
        self.ensure_one()
        has_allowance = bool(
            self.allowance_rule_ids.filtered('active')
            or (self.allowance_plan_id and self.allowance_plan_id.active)
        )
        is_staff = bool(
            has_allowance
            or ('employee_ids' in self._fields and self.employee_ids)
        )
        extras.update({
            'has_allowance': has_allowance,
            'is_staff': is_staff,
        })
        return extras

    def _app_summary_extras(self):
        extras = super()._app_summary_extras()
        self.ensure_one()
        has_allowance = bool(
            self.allowance_rule_ids.filtered('active')
            or (self.allowance_plan_id and self.allowance_plan_id.active)
        )
        extras.update({
            'has_allowance': has_allowance,
            'allowance_status': self.allowance_status or 'none',
            'allowance_summary': self.allowance_summary or '',
        })
        return extras

    def _app_allowance_extras(self):
        self.ensure_one()
        Rule = self.env['staff.allowance.rule'].sudo()
        categories = Rule.search([('partner_id', '=', self.id)]).pos_category_id
        plan = self.sudo().allowance_plan_id
        if plan and plan.active:
            categories |= plan.line_ids.pos_category_id
        limits = []
        for category in categories.sorted('name'):
            evaluation = Rule._evaluate(self, category)
            limits.append({
                'category_id': category.id,
                'category': category.display_name,
                'limit': evaluation['limit'],
                'used': evaluation['used'],
                'remaining': evaluation['remaining'],
                'at_the_limit': evaluation['policy'],
                'from_plan': evaluation['origin'] == 'plan',
                'resets_at': evaluation['resets_at'],
            })
        has_allowance = bool(limits)
        return {
            'has_allowance': has_allowance,
            'status': getattr(self, 'allowance_status', None) or ('active' if has_allowance else 'none'),
            'summary': getattr(self, 'allowance_summary', None) or '',
            'limits': limits,
        }

