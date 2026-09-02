# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    partner_ledger_count = fields.Integer(
        string="Statement Entries",
        compute="_compute_partner_ledger_count",
        help="Number of posted transactions for this partner."
    )

    def _compute_partner_ledger_count(self):
        """Compute the number of posted journal entries for this partner."""
        for partner in self:
            partner.partner_ledger_count = self.env['account.move.line'].search_count([
                ('partner_id', '=', partner.id),
                ('parent_state', '=', 'posted'),
            ])

    def action_open_partner_ledger_wizard(self):
        """Open the Customer Account Statement on-screen view and PDF generator."""
        self.ensure_one()
        wizard = self.env['hotel.partner.ledger.wizard'].create({
            'partner_id': self.id,
            'statement_date': fields.Date.context_today(self),
        })
        wizard._compute_statement_data()
        return {
            'name': f"Customer Account Statement - {self.name}",
            'type': 'ir.actions.act_window',
            'res_model': 'hotel.partner.ledger.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_partner_id': self.id,
            },
        }
