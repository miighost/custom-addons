# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    partner_ledger_count = fields.Integer(
        string="Statement Entries",
        compute="_compute_partner_ledger_data",
        help="Number of posted transactions for this partner."
    )
    partner_statement_balance = fields.Monetary(
        string="Statement Balance",
        compute="_compute_partner_ledger_data",
        currency_field="currency_id",
        help="Current outstanding statement balance for this partner."
    )

    def _compute_partner_ledger_data(self):
        """Compute posted journal count and statement balance for this partner."""
        for partner in self:
            domain = [
                ('partner_id', '=', partner.id),
                ('parent_state', '=', 'posted'),
                ('account_id.account_type', 'in', ['asset_receivable', 'liability_payable']),
            ]
            lines = self.env['account.move.line'].search(domain)
            partner.partner_ledger_count = len(lines)
            partner.partner_statement_balance = sum(lines.mapped('debit')) - sum(lines.mapped('credit'))

    def action_open_partner_ledger_wizard(self):
        """Open the Customer Account Statement on-screen view and PDF generator."""
        self.ensure_one()
        wizard = self.env['hotel.partner.ledger.wizard'].create({
            'partner_id': self.id,
            'statement_date': fields.Date.context_today(self),
        })
        wizard._load_statement_lines()
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
