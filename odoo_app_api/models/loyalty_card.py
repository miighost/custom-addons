from odoo import api, fields, models


class LoyaltyCard(models.Model):
    _inherit = 'loyalty.card'

    # res.partner.barcode is company-dependent, so a plain related field to it
    # is neither stored nor searchable. Compute a display copy instead - it is
    # only ever shown, never filtered on.
    partner_barcode = fields.Char(
        string='Membership Code', compute='_compute_partner_barcode')
    partner_phone = fields.Char(related='partner_id.phone', string='Phone')
    partner_email = fields.Char(related='partner_id.email', string='Email')

    is_app_customer = fields.Boolean(
        string='Uses the App', compute='_compute_is_app_customer', store=True)

    # Stored so the list can sort and total them.
    last_activity = fields.Datetime(
        string='Last Movement', compute='_compute_activity', store=True)
    topped_up_total = fields.Float(
        string='Topped Up', compute='_compute_activity', store=True)
    spent_total = fields.Float(
        string='Spent', compute='_compute_activity', store=True)

    @api.depends('partner_id')
    def _compute_partner_barcode(self):
        for card in self:
            card.partner_barcode = card.partner_id.barcode or ''

    @api.depends('partner_id', 'partner_id.firebase_uid')
    def _compute_is_app_customer(self):
        for card in self:
            card.is_app_customer = bool(card.partner_id.firebase_uid)

    @api.depends('history_ids', 'history_ids.issued', 'history_ids.used')
    def _compute_activity(self):
        for card in self:
            history = card.history_ids
            card.last_activity = max(history.mapped('create_date'),
                                     default=False)
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
