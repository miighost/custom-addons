# -*- coding: utf-8 -*-
from odoo import api, models


class ReportDailyCash(models.AbstractModel):
    """Abstract model for generating Cash Report / Daily Collections & POS Transactions QWeb PDF Report."""

    _name = "report.hotel_management_odoo.report_daily_cash"
    _description = "Daily Cash & POS Report Parser"

    @api.model
    def _get_report_values(self, docids, data=None):
        if data and data.get("cash_data"):
            cash_data = data["cash_data"]
        else:
            wizard = self.env["daily.cash.report.wizard"].browse(docids[0]) if docids else False
            cash_data = wizard.generate_data() if wizard else {"period": "-", "total_records": 0, "total_debit": "0.00", "total_credit": "0.00", "closing_balance": "0.00", "method_summary": [], "lines": []}

        return {
            "doc_ids": docids,
            "doc_model": "daily.cash.report.wizard",
            "cash_data": cash_data,
            "period": cash_data.get("period", "-"),
            "total_records": cash_data.get("total_records", 0),
            "total_debit": cash_data.get("total_debit", "0.00"),
            "total_credit": cash_data.get("total_credit", "0.00"),
            "closing_balance": cash_data.get("closing_balance", "0.00"),
            "method_summary": cash_data.get("method_summary", []),
            "lines": cash_data.get("lines", []),
        }
