from odoo import http
from odoo.http import request

from odoo.addons.odoo_app_api.controllers.main import ROUTE, api_endpoint


class AppAllowance(http.Controller):

    @http.route('/api/v1/allowance', **ROUTE)
    @api_endpoint
    def allowance(self, partner, payload):
        """The customer's daily limits and what is left of them today."""
        Rule = request.env['staff.allowance.rule'].sudo()
        categories = Rule.search([('partner_id', '=', partner.id)]).pos_category_id
        plan = partner.sudo().allowance_plan_id
        if plan.active:
            categories |= plan.line_ids.pos_category_id
        limits = []
        for category in categories.sorted('name'):
            evaluation = Rule._evaluate(partner, category)
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
        return {'has_allowance': bool(limits), 'limits': limits}
