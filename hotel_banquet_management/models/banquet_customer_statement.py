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


class BanquetCustomerStatementWizard(models.TransientModel):
    _name = 'banquet.customer.statement.wizard'
    _description = 'Banquet Customer Statement Wizard'

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

    def action_print_statement(self):
        self.ensure_one()
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValidationError(_("From Date cannot be greater than To Date."))
        return self.env.ref('hotel_banquet_management.action_report_banquet_customer_statement').report_action(self)

    def get_statement_data(self):
        self.ensure_one()
        partner = self.partner_id
        company_id = self.company_id.id
        date_from = self.date_from
        date_to = self.date_to

        # 1. Fetch Banquet Orders
        orders = self.env['sale.order'].search([
            ('is_banquet', '=', True),
            ('partner_id', '=', partner.id),
            ('company_id', '=', company_id),
            ('date_order', '>=', datetime.combine(date_from, datetime.min.time())),
            ('date_order', '<=', datetime.combine(date_to, datetime.max.time())),
            ('state', 'in', ['sale', 'done'])
        ], order='date_order asc')

        # 2. Fetch Customer Invoices
        invoices = self.env['account.move'].search([
            ('partner_id', '=', partner.id),
            ('company_id', '=', company_id),
            ('move_type', '=', 'out_invoice'),
            ('invoice_date', '>=', date_from),
            ('invoice_date', '<=', date_to),
            ('state', '=', 'posted')
        ], order='invoice_date asc')

        statement_lines = []
        running_balance = 0.0
        total_invoiced = 0.0
        total_paid = 0.0

        for inv in invoices:
            invoiced_amt = inv.amount_total
            paid_amt = inv.amount_total - inv.amount_residual
            due_amt = inv.amount_residual
            total_invoiced += invoiced_amt
            total_paid += paid_amt
            running_balance += due_amt

            statement_lines.append({
                'date': inv.invoice_date.strftime('%d/%m/%Y') if inv.invoice_date else '',
                'ref': inv.name or '',
                'desc': inv.ref or (inv.invoice_line_ids[0].name if inv.invoice_line_ids else 'Banquet Invoice'),
                'due_date': inv.invoice_date_due.strftime('%d/%m/%Y') if inv.invoice_date_due else '',
                'invoiced': invoiced_amt,
                'paid': paid_amt,
                'balance': due_amt,
                'status': dict(inv._fields['payment_state'].selection).get(inv.payment_state, 'Not Paid')
            })

        return {
            'partner': partner,
            'company': self.company_id,
            'date_from': date_from.strftime('%d/%m/%Y'),
            'date_to': date_to.strftime('%d/%m/%Y'),
            'orders_count': len(orders),
            'total_invoiced': total_invoiced,
            'total_paid': total_paid,
            'total_due': running_balance,
            'lines': statement_lines,
        }
