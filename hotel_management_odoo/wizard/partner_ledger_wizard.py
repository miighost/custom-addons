# -*- coding: utf-8 -*-
from datetime import datetime
from odoo import api, fields, models


class HotelPartnerLedgerWizard(models.TransientModel):
    """Wizard & On-Screen Interactive Customer Account Statement."""

    _name = "hotel.partner.ledger.wizard"
    _description = "Customer Account Statement Wizard"

    partner_id = fields.Many2one("res.partner", string="Customer", required=True)
    ref_number = fields.Char(string="Ref Number", compute="_compute_ref_number", store=True, readonly=False)
    statement_date = fields.Date(string="Statement Date", default=fields.Date.context_today)
    date_from = fields.Date(string="From Date")
    date_to = fields.Date(string="To Date")
    opening_balance = fields.Float(string="Opening Balance", compute="_compute_statement_data", store=True, digits=(16, 2))
    total_debit = fields.Float(string="Total Debit", compute="_compute_statement_data", store=True, digits=(16, 2))
    total_credit = fields.Float(string="Total Credit", compute="_compute_statement_data", store=True, digits=(16, 2))
    ending_balance = fields.Float(string="Ending Balance", compute="_compute_statement_data", store=True, digits=(16, 2))
    line_ids = fields.One2many("hotel.partner.statement.line", "wizard_id", string="Statement Lines", compute="_compute_statement_data", store=True)

    @api.depends('partner_id')
    def _compute_ref_number(self):
        for rec in self:
            if rec.partner_id:
                rec.ref_number = rec.partner_id.ref or f"{rec.partner_id.id}"
            else:
                rec.ref_number = "-"

    @api.depends('partner_id', 'date_from', 'date_to', 'statement_date')
    def _compute_statement_data(self):
        """Compute Opening Balance, Statement Lines, and Running Balance on screen."""
        for wizard in self:
            if not wizard.partner_id:
                wizard.opening_balance = 0.0
                wizard.total_debit = 0.0
                wizard.total_credit = 0.0
                wizard.ending_balance = 0.0
                wizard.line_ids = [(5, 0, 0)]
                continue

            partner = wizard.partner_id

            # 1. Opening Balance (All posted entries before date_from)
            initial_balance = 0.0
            if wizard.date_from:
                prior_domain = [
                    ('partner_id', '=', partner.id),
                    ('parent_state', '=', 'posted'),
                    ('date', '<', wizard.date_from),
                ]
                prior_lines = self.env['account.move.line'].search(prior_domain)
                receivable_prior = prior_lines.filtered(lambda l: l.account_id.account_type in ['asset_receivable', 'liability_payable'])
                if receivable_prior:
                    initial_balance = sum(receivable_prior.mapped('debit')) - sum(receivable_prior.mapped('credit'))
                else:
                    initial_balance = sum(prior_lines.mapped('debit')) - sum(prior_lines.mapped('credit'))

            # 2. Period Lines (date_from <= date <= date_to)
            period_domain = [
                ('partner_id', '=', partner.id),
                ('parent_state', '=', 'posted'),
            ]
            if wizard.date_from:
                period_domain.append(('date', '>=', wizard.date_from))
            if wizard.date_to:
                period_domain.append(('date', '<=', wizard.date_to))

            move_lines = self.env['account.move.line'].search(period_domain, order='date asc, id asc')
            rec_lines = move_lines.filtered(lambda l: l.account_id.account_type in ['asset_receivable', 'liability_payable'])
            if not rec_lines and move_lines:
                rec_lines = move_lines

            running_balance = initial_balance
            lines_commands = [(5, 0, 0)]
            tot_debit = 0.0
            tot_credit = 0.0

            for line in rec_lines:
                debit = line.debit or 0.0
                credit = line.credit or 0.0
                tot_debit += debit
                tot_credit += credit
                running_balance += (debit - credit)

                # Format clean description matching sample
                desc = ""
                if line.move_id and line.move_id.pos_order_ids:
                    pos = line.move_id.pos_order_ids[0]
                    receipt_no = pos.pos_reference or pos.name or line.move_id.name
                    desc = f"Food Charges Receipt # {receipt_no}"
                elif line.payment_id:
                    desc = f"Payment From {partner.name}"
                elif line.move_id.move_type == 'out_invoice':
                    desc = f"Invoice # {line.move_id.name}" if not line.ref else f"{line.ref} ({line.move_id.name})"
                elif line.name and line.name != '/':
                    desc = line.name
                elif line.ref:
                    desc = line.ref
                else:
                    desc = line.move_id.name or "Transaction"

                lines_commands.append((0, 0, {
                    'description': desc,
                    'trans_date': line.date,
                    'debit': debit,
                    'credit': credit,
                    'rtotal': running_balance,
                    'move_id': line.move_id.id,
                }))

            wizard.opening_balance = initial_balance
            wizard.total_debit = tot_debit
            wizard.total_credit = tot_credit
            wizard.ending_balance = running_balance
            wizard.line_ids = lines_commands

    def action_print_pdf(self):
        """Generate PDF Statement matching exact sample layout."""
        self.ensure_one()
        data = {
            'ledger_data': self.get_report_data(),
        }
        return self.env.ref("hotel_management_odoo.action_report_partner_ledger").report_action(self, data=data)

    def get_report_data(self):
        """Return structured dictionary for QWeb PDF report."""
        self.ensure_one()
        self._compute_statement_data()
        stmt_date = self.statement_date.strftime("%d/%m/%Y") if self.statement_date else datetime.now().strftime("%d/%m/%Y")

        lines_data = []
        for l in self.line_ids:
            lines_data.append({
                'description': l.description,
                'trans_date': l.trans_date.strftime("%d/%m/%Y") if l.trans_date else "-",
                'debit': l.debit,
                'credit': l.credit,
                'rtotal': l.rtotal,
            })

        return {
            'partner': {
                'name': self.partner_id.name,
                'ref': self.ref_number or self.partner_id.ref or f"{self.partner_id.id}",
                'statement_date': stmt_date,
            },
            'opening_balance': self.opening_balance,
            'lines': lines_data,
            'total_period_debit': self.total_debit,
            'total_period_credit': self.total_credit,
            'ending_balance': self.ending_balance,
            'currency': self.env.company.currency_id,
        }


class HotelPartnerStatementLine(models.TransientModel):
    """Line items for on-screen Customer Account Statement."""

    _name = "hotel.partner.statement.line"
    _description = "Customer Statement Line"
    _order = "trans_date asc, id asc"

    wizard_id = fields.Many2one("hotel.partner.ledger.wizard", ondelete="cascade")
    description = fields.Char(string="Description")
    trans_date = fields.Date(string="Trans_Date")
    debit = fields.Float(string="Debit", digits=(16, 2))
    credit = fields.Float(string="Credit", digits=(16, 2))
    rtotal = fields.Float(string="RTotal1", digits=(16, 2))
    move_id = fields.Many2one("account.move", string="Journal Entry")
