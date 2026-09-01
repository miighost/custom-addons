# -*- coding: utf-8 -*-
#############################################################################
#
#    MiiG Solution
#
#    Copyright (C) 2026-TODAY MiiG Solution(<https://www.miigsolution.so>)
#    Author: MiiG Solution(<https://www.miigsolution.so>)
#
#    You can modify it under the terms of the GNU LESSER
#    GENERAL PUBLIC LICENSE (LGPL v3), Version 3.
#
#############################################################################
from datetime import datetime
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class BanquetPartnerLedgerWizard(models.TransientModel):
    _name = 'banquet.partner.ledger.wizard'
    _description = 'Banquet Customer / Partner Ledger Wizard'

    partner_id = fields.Many2one(
        'res.partner',
        string='Customer / Company',
        required=True,
        domain="['|', ('is_company', '=', True), ('customer_rank', '>', 0)]"
    )
    date_from = fields.Date(
        string='From Date',
        required=True,
        default=lambda self: fields.Date.today().replace(day=1)
    )
    date_to = fields.Date(
        string='To Date',
        required=True,
        default=fields.Date.context_today
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company
    )
    include_initial_balance = fields.Boolean(
        string='Include Initial Balance',
        default=True,
        help="Include previous period balance as opening balance."
    )

    def action_print_ledger(self):
        self.ensure_one()
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValidationError(_("From Date cannot be greater than To Date."))
        return self.env.ref('hotel_banquet_management.action_report_banquet_partner_ledger').report_action(self)

    def get_ledger_data(self):
        self.ensure_one()
        partner = self.partner_id
        company = self.company_id
        date_from = self.date_from
        date_to = self.date_to

        # Find receivable accounts for the partner
        domain_base = [
            ('partner_id', '=', partner.id),
            ('company_id', '=', company.id),
            ('move_id.state', '=', 'posted'),
            ('account_id.account_type', '=', 'asset_receivable'),
        ]

        # 1. Initial Balance (all posted receivable entries before date_from)
        initial_balance = 0.0
        if self.include_initial_balance and date_from:
            domain_initial = domain_base + [('date', '<', date_from)]
            initial_lines = self.env['account.move.line'].search(domain_initial)
            for il in initial_lines:
                initial_balance += (il.debit - il.credit)

        # 2. Period Transactions
        domain_period = domain_base + [
            ('date', '>=', date_from),
            ('date', '<=', date_to)
        ]
        move_lines = self.env['account.move.line'].search(domain_period, order='date asc, id asc')

        running_balance = initial_balance
        total_debit = 0.0
        total_credit = 0.0
        ledger_lines = []

        for line in move_lines:
            debit = line.debit or 0.0
            credit = line.credit or 0.0
            running_balance += (debit - credit)
            total_debit += debit
            total_credit += credit

            ledger_lines.append({
                'date': line.date.strftime('%d/%m/%Y') if line.date else '',
                'journal': line.journal_id.code or '',
                'ref': line.move_id.name or '',
                'desc': line.name or line.move_id.ref or (line.move_id.move_type == 'out_invoice' and 'Invoice') or 'Transaction',
                'matching_number': line.matching_number or '',
                'debit': debit,
                'credit': credit,
                'balance': running_balance,
            })

        return {
            'partner': partner,
            'company': company,
            'date_from': date_from.strftime('%d/%m/%Y'),
            'date_to': date_to.strftime('%d/%m/%Y'),
            'initial_balance': initial_balance,
            'lines': ledger_lines,
            'total_debit': total_debit,
            'total_credit': total_credit,
            'ending_balance': running_balance,
        }
