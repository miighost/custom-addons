from odoo import api, fields, models


class LoyaltyCard(models.Model):
    _inherit = 'loyalty.card'

    partner_email = fields.Char(related='partner_id.email', string='Email')
    partner_phone = fields.Char(related='partner_id.phone', string='Phone')
    partner_barcode = fields.Char(related='partner_id.barcode',
                                  string='Membership Code')
    is_app_customer = fields.Boolean(
        related='partner_id.is_app_user', string='Uses the App', store=True)

    last_activity = fields.Datetime(
        compute='_compute_activity', string='Last Movement')
    topped_up_total = fields.Float(
        compute='_compute_activity', string='Topped Up')
    spent_total = fields.Float(compute='_compute_activity', string='Spent')

    @api.depends('history_ids')
    def _compute_activity(self):
        for card in self:
            history = card.history_ids
            card.last_activity = max(history.mapped('create_date'), default=False)
            card.topped_up_total = sum(history.mapped('issued'))
            card.spent_total = sum(history.mapped('used'))

    def action_open_topup_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Top Up Wallet',
            'res_model': 'app.wallet.topup',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_partner_id': self.partner_id.id,
                'default_program_id': self.program_id.id,
            },
        }
