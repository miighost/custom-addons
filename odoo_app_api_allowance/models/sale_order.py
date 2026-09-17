import math

from odoo import fields, models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    allowance_order_ids = fields.One2many('staff.allowance.order', 'sale_order_id',
                                          string='Allowance Entries')

    def _app_allowance_lines(self):
        return [{'product_id': line.product_id.id, 'qty': line.product_uom_qty}
                for line in self.order_line
                if line.product_id and not line.display_type and not line.is_reward_line]

    def _app_check_allowance(self):
        """The same check the POS makes at Validate, logged as an app attempt."""
        result = super()._app_check_allowance()
        basket = self.env['staff.allowance.rule'].sudo().check_pos_basket(
            self.partner_id.id, self._app_allowance_lines(), source='app')
        return {
            'blocked': result['blocked'] or basket['blocked'],
            'messages': result['messages'] + basket['messages'],
            'warnings': result['warnings'] + basket['warnings'],
        }

    def action_confirm(self):
        result = super().action_confirm()
        self.filtered('is_app_order')._record_app_allowance()
        return result

    def _action_cancel(self):
        # A cancelled order never happened: give the allowance back.
        self.allowance_order_ids.sudo().unlink()
        return super()._action_cancel()

    def _record_app_allowance(self):
        """A confirmed app order counts against the allowance, like a paid POS sale."""
        Allowance = self.env['staff.allowance.order'].sudo()
        Rule = self.env['staff.allowance.rule'].sudo()
        for order in self:
            order.allowance_order_ids.sudo().unlink()
            for line in order.order_line:
                if (not line.product_id or line.display_type or line.is_reward_line
                        or line.product_uom_qty <= 0):
                    continue
                for category in Rule._counted_categories(order.partner_id, line.product_id):
                    Allowance.create({
                        'partner_id': order.partner_id.id,
                        'pos_category_id': category.id,
                        'product_id': line.product_id.id,
                        'qty': math.ceil(line.product_uom_qty),
                        'source': 'app',
                        'state': 'done',
                        'sale_order_id': order.id,
                        'order_datetime': order.date_order or fields.Datetime.now(),
                    })
