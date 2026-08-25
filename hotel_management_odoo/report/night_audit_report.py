# -*- coding: utf-8 -*-
from odoo import api, models


class ReportNightAudit(models.AbstractModel):
    """Abstract model for generating Consolidated 24-Hour Night Audit Pack QWeb PDF Report."""

    _name = "report.hotel_management_odoo.report_night_audit"
    _description = "Night Audit Pack Report Parser"

    @api.model
    def _get_report_values(self, docids, data=None):
        if data and data.get("audit_data"):
            audit_data = data["audit_data"]
        else:
            rec = False
            if docids:
                active_model = self.env.context.get("active_model", "")
                if active_model == "hotel.night.audit" or self.env["hotel.night.audit"].browse(docids[0]).exists():
                    rec = self.env["hotel.night.audit"].browse(docids[0])
                else:
                    rec = self.env["night.audit.wizard"].browse(docids[0])
            audit_data = rec.generate_night_audit_data() if rec else {}

        return {
            "doc_ids": docids,
            "doc_model": "night.audit.wizard",
            "audit_data": audit_data,
            "cover": audit_data.get("cover", {}),
            "kpis": audit_data.get("kpis", {}),
            "inhouse_list": audit_data.get("inhouse_list", []),
            "arrivals_list": audit_data.get("arrivals_list", []),
            "departures_list": audit_data.get("departures_list", []),
            "daily_rent_list": audit_data.get("daily_rent_list", []),
            "cash_lines": audit_data.get("cash_lines", []),
            "method_summary": audit_data.get("method_summary", []),
            "total_debit": audit_data.get("total_debit", "0.00"),
            "total_credit": audit_data.get("total_credit", "0.00"),
            "closing_balance": audit_data.get("closing_balance", "0.00"),
        }
