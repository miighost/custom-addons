# -*- coding: utf-8 -*-
from odoo import api, models


class ReportRoomAnalysis(models.AbstractModel):
    """Abstract model for generating Room Analysis Summary QWeb PDF Report."""

    _name = "report.hotel_management_odoo.report_room_analysis"
    _description = "Room Analysis Report Parser"

    @api.model
    def _get_report_values(self, docids, data=None):
        if data and data.get("analysis_data"):
            anl = data["analysis_data"]
        else:
            wizard = self.env["room.analysis.wizard"].browse(docids[0]) if docids else False
            anl = wizard.generate_data() if wizard else {"date": "-", "kpis": {}, "room_breakdown": []}

        return {
            "doc_ids": docids,
            "doc_model": "room.analysis.wizard",
            "anl": anl,
            "date": anl.get("date", "-"),
            "kpis": anl.get("kpis", {}),
            "room_breakdown": anl.get("room_breakdown", []),
        }
