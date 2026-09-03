from odoo import models


class LoyaltyCard(models.Model):
    _inherit = 'loyalty.card'

    def action_open_topup_wizard(self):
        """Opened from the Top Up Wallet entry in the Actions menu."""
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
