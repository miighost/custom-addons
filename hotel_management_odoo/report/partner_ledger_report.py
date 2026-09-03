# -*- coding: utf-8 -*-
from odoo import api, models


class ReportPartnerLedger(models.AbstractModel):
    """Report Parser for Customer Account Statement PDF Report."""

    _name = 'report.hotel_management_odoo.report_partner_ledger'
    _description = 'Customer Account Statement Report Parser'

    @api.model
    def _get_report_values(self, docids, data=None):
        if data and data.get('ledger_data'):
            ledger = data['ledger_data']
        else:
            wizard = self.env['hotel.partner.ledger.wizard'].browse(docids[0]) if docids else False
            ledger = wizard.get_report_data() if wizard else {}

        return {
            'doc_ids': docids,
            'doc_model': 'hotel.partner.ledger.wizard',
            'ledger': ledger,
            'partner': ledger.get('partner', {}),
            'opening_balance': ledger.get('opening_balance', '0.00'),
            'lines': ledger.get('lines', []),
            'total_period_debit': ledger.get('total_period_debit', '0.00'),
            'total_period_credit': ledger.get('total_period_credit', '0.00'),
            'ending_balance': ledger.get('ending_balance', '0.00'),
            'currency': ledger.get('currency', self.env.company.currency_id),
        }
