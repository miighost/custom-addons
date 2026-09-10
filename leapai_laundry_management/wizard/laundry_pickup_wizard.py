from odoo import models, fields, _


class LaundryPickupWizard(models.TransientModel):
    _name = 'laundry.pickup.wizard'
    _description = 'Pickup / Delivery Wizard'

    order_id = fields.Many2one('laundry.order', string='Order', required=True)
    order_type = fields.Selection([('pickup', 'Pick Up'), ('delivery', 'Home Delivery')], string='Type')
    staff_name = fields.Char(string='Staff Name', required=True)
    staff_phone = fields.Char(string='Staff Phone')
    notes = fields.Text(string='Notes')

    def action_confirm(self):
        self.ensure_one()
        order = self.order_id
        order.staff_name = self.staff_name
        order.staff_phone = self.staff_phone
        order.state = 'picked_up'
        order.picked_up_date = fields.Datetime.now()
        msg = _('Clothes %s by %s (%s)') % (
            'delivered' if order.order_type == 'delivery' else 'picked up',
            self.staff_name,
            self.staff_phone or '-'
        )
        order.message_post(body=msg)
        return {'type': 'ir.actions.act_window_close'}
