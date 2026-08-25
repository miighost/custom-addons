# -*- coding: utf-8 -*-
from odoo import api, models


class ReportDailyRoomCharges(models.AbstractModel):
    """Abstract model for generating Daily Rent / Room Charges QWeb PDF Report."""

    _name = "report.hotel_management_odoo.report_daily_room_charges"
    _description = "Daily Room Charges Report Parser"

    @api.model
    def _get_report_values(self, docids, data=None):
        if data and data.get("charges_data"):
            charges_data = data["charges_data"]
        else:
            wizard = self.env["daily.room.charges.wizard"].browse(docids[0]) if docids else False
            charges_data = wizard.generate_data() if wizard else {"date": "-", "total_rooms": 0, "total_pax": 0, "total_rent": "0.00", "lines": []}

        return {
            "doc_ids": docids,
            "doc_model": "daily.room.charges.wizard",
            "charges_data": charges_data,
            "date": charges_data.get("date", "-"),
            "total_rooms": charges_data.get("total_rooms", 0),
            "total_pax": charges_data.get("total_pax", 0),
            "total_rent": charges_data.get("total_rent", "0.00"),
            "lines": charges_data.get("lines", []),
        }
