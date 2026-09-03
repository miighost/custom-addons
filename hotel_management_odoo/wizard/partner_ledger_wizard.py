# -*- coding: utf-8 -*-
from datetime import datetime
from odoo import api, fields, models


class HotelPartnerLedgerWizard(models.TransientModel):
    """Wizard & On-Screen Interactive Customer Account Statement."""

    _name = "hotel.partner.ledger.wizard"
    _description = "Customer Account Statement Wizard"

    partner_id = fields.Many2one("res.partner", string="Customer", required=True)
    partner_phone = fields.Char(related="partner_id.phone", string="Phone", readonly=True)
    partner_email = fields.Char(related="partner_id.email", string="Email", readonly=True)
    currency_id = fields.Many2one("res.currency", string="Currency", default=lambda self: self.env.company.currency_id)
    ref_number = fields.Char(string="Ref Number")
    statement_date = fields.Date(string="Statement Date", default=fields.Date.context_today)
    date_from = fields.Date(string="From Date")
    date_to = fields.Date(string="To Date")
    opening_balance = fields.Monetary(string="Opening Balance", currency_field="currency_id", digits=(16, 2))
    total_debit = fields.Monetary(string="Total Debit", currency_field="currency_id", digits=(16, 2))
    total_credit = fields.Monetary(string="Total Credit", currency_field="currency_id", digits=(16, 2))
    ending_balance = fields.Monetary(string="Ending Balance", currency_field="currency_id", digits=(16, 2))
    line_ids = fields.One2many("hotel.partner.statement.line", "wizard_id", string="Statement Lines")

    def _extract_receipt_no(self, pos, line):
        """Extract ONLY the clean numeric receipt/ticket number, stripping prefixes like 'Restaurant/' or 'POS/'."""
        if pos:
            # 1. Ticket tracking number (e.g. 18, 372732)
            if getattr(pos, 'tracking_number', False) and pos.tracking_number:
                return str(pos.tracking_number).strip()

            # 2. Sequential receipt number
            if getattr(pos, 'sequence_number', False) and pos.sequence_number:
                return str(pos.sequence_number).strip()

            # 3. Receipt reference from pos_reference
            if getattr(pos, 'pos_reference', False) and pos.pos_reference:
                ref = str(pos.pos_reference).strip()
                if 'Receipt' in ref:
                    ref = ref.split('Receipt')[-1].replace('#', '').strip()
                if '/' in ref:
                    ref = ref.split('/')[-1].strip()
                if '-' in ref:
                    ref = ref.split('-')[-1].strip()
                clean = ref.replace('Order ', '').replace('Order', '').replace('POS', '').replace('Restaurant', '').strip()
                if clean:
                    return clean

            # 4. From pos.name (e.g. 'Restaurant/00018' -> '00018')
            if getattr(pos, 'name', False) and pos.name:
                name_str = str(pos.name).strip()
                if '/' in name_str:
                    return name_str.split('/')[-1].strip()
                return name_str

        # Fallback from move_line reference
        if line:
            ref = (line.ref or line.name or (line.move_id and line.move_id.name) or '').strip()
            if 'Receipt' in ref:
                ref = ref.split('Receipt')[-1].replace('#', '').strip()
            if '/' in ref:
                ref = ref.split('/')[-1].strip()
            if '-' in ref:
                ref = ref.split('-')[-1].strip()
            clean = ref.replace('Order ', '').replace('Order', '').replace('POS', '').replace('Restaurant', '').strip()
            if clean and clean != '/':
                return clean

        return ""

    def _load_statement_lines(self):
        """Populate opening balance, ledger lines, and summary totals."""
        for wizard in self:
            if not wizard.partner_id:
                wizard.opening_balance = 0.0
                wizard.total_debit = 0.0
                wizard.total_credit = 0.0
                wizard.ending_balance = 0.0
                wizard.line_ids.unlink()
                continue

            partner = wizard.partner_id
            wizard.ref_number = partner.ref or f"{partner.id}"

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

            # Remove prior lines cleanly
            wizard.line_ids.unlink()

            running_balance = initial_balance
            tot_debit = 0.0
            tot_credit = 0.0
            new_lines = []
            curr_id = wizard.currency_id.id or self.env.company.currency_id.id

            for line in rec_lines:
                debit = line.debit or 0.0
                credit = line.credit or 0.0
                tot_debit += debit
                tot_credit += credit
                running_balance += (debit - credit)

                # Format Description: Food Receipt # [Clean Receipt No]
                desc = ""
                pos_orders = getattr(line.move_id, 'pos_order_ids', False)
                if line.move_id and pos_orders and len(pos_orders) > 0:
                    pos = pos_orders[0]
                    rcpt_no = self._extract_receipt_no(pos, line)
                    desc = f"Food Receipt # {rcpt_no}" if rcpt_no else "Food Receipt"
                elif line.payment_id:
                    desc = f"Payment From {partner.name}"
                elif line.move_id and ('POS' in (line.move_id.name or '') or 'POS' in (line.ref or '') or 'Food' in (line.name or '') or 'Restaurant' in (line.name or '') or 'Restaurant' in (line.move_id.name or '')):
                    rcpt_no = self._extract_receipt_no(False, line)
                    desc = f"Food Receipt # {rcpt_no}" if rcpt_no else "Food Receipt"
                elif line.move_id.move_type == 'out_invoice':
                    desc = f"Invoice # {line.move_id.name}" if not line.ref else f"{line.ref} ({line.move_id.name})"
                elif line.name and line.name != '/':
                    desc = line.name
                elif line.ref:
                    desc = line.ref
                else:
                    desc = line.move_id.name or "Transaction"

                new_lines.append({
                    'wizard_id': wizard.id,
                    'currency_id': curr_id,
                    'description': desc,
                    'trans_date': line.date,
                    'debit': debit,
                    'credit': credit,
                    'rtotal': running_balance,
                    'move_id': line.move_id.id,
                })

            if new_lines:
                self.env['hotel.partner.statement.line'].create(new_lines)

            wizard.opening_balance = initial_balance
            wizard.total_debit = tot_debit
            wizard.total_credit = tot_credit
            wizard.ending_balance = running_balance

    def action_refresh(self):
        """Reload and apply date filters."""
        self.ensure_one()
        self._load_statement_lines()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'hotel.partner.ledger.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_print_pdf(self):
        """Generate PDF Statement matching exact sample layout."""
        self.ensure_one()
        self._load_statement_lines()
        data = {
            'ledger_data': self.get_report_data(),
        }
        return self.env.ref("hotel_management_odoo.action_report_partner_ledger").report_action(self, data=data)

    def action_view_partner(self):
        """Navigate back to the partner form view."""
        self.ensure_one()
        return {
            'name': self.partner_id.name,
            'type': 'ir.actions.act_window',
            'res_model': 'res.partner',
            'res_id': self.partner_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def get_report_data(self):
        """Return pre-formatted dictionary for QWeb PDF report."""
        self.ensure_one()
        stmt_date = self.statement_date.strftime("%d/%m/%Y") if self.statement_date else datetime.now().strftime("%d/%m/%Y")

        lines_data = []
        for l in self.line_ids.exists():
            lines_data.append({
                'description': l.description or '-',
                'trans_date': l.trans_date.strftime("%d/%m/%Y") if l.trans_date else "-",
                'debit': f"{l.debit:,.2f}",
                'credit': f"{l.credit:,.2f}",
                'rtotal': f"{l.rtotal:,.2f}",
            })

        return {
            'partner': {
                'name': self.partner_id.name or '-',
                'ref': self.ref_number or self.partner_id.ref or f"{self.partner_id.id}",
                'statement_date': stmt_date,
            },
            'opening_balance': f"{self.opening_balance:,.2f}",
            'lines': lines_data,
            'total_period_debit': f"{self.total_debit:,.2f}",
            'total_period_credit': f"{self.total_credit:,.2f}",
            'ending_balance': f"{self.ending_balance:,.2f}",
            'currency': self.env.company.currency_id,
        }


class HotelPartnerStatementLine(models.TransientModel):
    """Line items for on-screen Customer Account Statement."""

    _name = "hotel.partner.statement.line"
    _description = "Customer Statement Line"
    _order = "trans_date asc, id asc"

    wizard_id = fields.Many2one("hotel.partner.ledger.wizard", ondelete="cascade")
    currency_id = fields.Many2one("res.currency", string="Currency", default=lambda self: self.env.company.currency_id)
    description = fields.Char(string="Description")
    trans_date = fields.Date(string="Trans_Date")
    debit = fields.Monetary(string="Debit", currency_field="currency_id")
    credit = fields.Monetary(string="Credit", currency_field="currency_id")
    rtotal = fields.Monetary(string="RTotal1", currency_field="currency_id")
    move_id = fields.Many2one("account.move", string="Journal Entry")
