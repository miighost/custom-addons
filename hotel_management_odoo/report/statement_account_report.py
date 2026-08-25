# -*- coding: utf-8 -*-
from odoo import api, models


class ReportStatementAccount(models.AbstractModel):
    """Abstract model for generating Statement of Account QWeb PDF Report."""

    _name = 'report.hotel_management_odoo.report_statement_account'
    _description = 'Statement of Account Report Parser'

    @api.model
    def _get_report_values(self, docids, data=None):
        if data and data.get('statement'):
            stmt = data['statement']
        else:
            wizard = self.env['statement.account.wizard'].browse(docids[0]) if docids else False
            stmt = wizard.generate_statement_data() if wizard else {'header': {}, 'lines': []}

        return {
            'doc_ids': docids,
            'doc_model': 'statement.account.wizard',
            'stmt': stmt,
            'header': stmt.get('header', {}),
            'lines': stmt.get('lines', []),
        }
