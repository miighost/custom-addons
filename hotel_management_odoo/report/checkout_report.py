# -*- coding: utf-8 -*-
from odoo import api, models


class ReportCheckout(models.AbstractModel):
    """Abstract model for generating Check Out QWeb PDF Report."""

    _name = "report.hotel_management_odoo.report_checkout"
    _description = "Check Out Report Parser"

    @api.model
    def _get_report_values(self, docids, data=None):
        if data and data.get("checkout_data"):
            chk_data = data["checkout_data"]
        else:
            wizard = self.env["checkout.report.wizard"].browse(docids[0]) if docids else False
            chk_data = wizard.generate_data() if wizard else {"period": "-", "total_records": 0, "total_rate": "0.00", "lines": []}

        return {
            "doc_ids": docids,
            "doc_model": "checkout.report.wizard",
            "chk_data": chk_data,
            "period": chk_data.get("period", "-"),
            "total_records": chk_data.get("total_records", 0),
            "total_rate": chk_data.get("total_rate", "0.00"),
            "lines": chk_data.get("lines", []),
        }
