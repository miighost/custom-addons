# -*- coding: utf-8 -*-
#############################################################################
#
#    Cybrosys Technologies Pvt. Ltd.
#
#    Copyright (C) 2026-TODAY Cybrosys Technologies(<https://www.cybrosys.com>)
#    Author: Cybrosys Techno Solutions(<https://www.cybrosys.com>)
#
#    You can modify it under the terms of the GNU LESSER
#    GENERAL PUBLIC LICENSE (LGPL v3), Version 3.
#
#############################################################################
import io
import json
from datetime import datetime, time
from odoo import fields, models
from odoo.tools import json_default

try:
    from odoo.tools.misc import xlsxwriter
except ImportError:
    import xlsxwriter


class DailyRoomChargesWizard(models.TransientModel):
    """Wizard for generating Daily Rent / Room Charges Report."""

    _name = "daily.room.charges.wizard"
    _description = "Daily Room Charges Report Wizard"

    date = fields.Date(string="Date", default=fields.Date.context_today, required=True, help="Select the day for room charges")
    partner_id = fields.Many2one("res.partner", string="Guest / Company", help="Optional filter by guest or company")

    def action_print_pdf(self):
        """Generate PDF Daily Rent / Room Charges Report."""
        data = {
            "charges_data": self.generate_data(),
        }
        return self.env.ref("hotel_management_odoo.action_report_daily_room_charges").report_action(self, data=data)

    def action_print_excel(self):
        """Generate Excel Daily Rent / Room Charges Report."""
        data = {
            "charges_data": self.generate_data(),
        }
        return {
            "type": "ir.actions.report",
            "data": {
                "model": "daily.room.charges.wizard",
                "options": json.dumps(data, default=json_default),
                "output_format": "xlsx",
                "report_name": "Daily Room Charges Report",
            },
            "report_type": "xlsx",
        }

    def generate_data(self):
        """Fetch and calculate daily room charges for in-house / active bookings on the selected date."""
        self.ensure_one()
        dt_start = datetime.combine(self.date, time.min)
        dt_end = datetime.combine(self.date, time.max)

        domain = [
            ("checkin_date", "<=", dt_end),
            ("checkout_date", ">=", dt_start),
            ("state", "in", ["check_in", "reserved", "check_out", "done"]),
        ]
        if self.partner_id:
            domain.append(("partner_id", "=", self.partner_id.id))

        bookings = self.env["room.booking"].search(domain, order="name asc")

        lines = []
        s_no = 1
        total_rent = 0.0
        total_pax = 0

        for b in bookings:
            for rline in b.room_line_ids:
                # Check if this specific room line was active on the selected date
                r_in = rline.checkin_date or b.checkin_date
                r_out = rline.checkout_date or b.checkout_date
                if r_in and r_in > dt_end:
                    continue
                if r_out and r_out < dt_start:
                    continue

                pax = rline.room_id.num_person if (rline.room_id and rline.room_id.num_person) else 1
                company_name = b.partner_id.parent_id.name if b.partner_id.parent_id else (b.partner_id.company_name or "ACCOUNT DIRECT")
                rent = rline.price_unit if rline.price_unit else (rline.price_subtotal / (b.duration or 1) if b.duration else rline.price_subtotal)
                total_rent += rent
                total_pax += pax

                checkin_str = (r_in or b.checkin_date).strftime("%d/%m/%Y") if (r_in or b.checkin_date) else "-"

                lines.append({
                    "s_no": s_no,
                    "name": b.partner_id.name or "-",
                    "room_no": rline.room_id.name if rline.room_id else (b.room_name or "-"),
                    "card_no": b.name or "-",
                    "check_in": checkin_str,
                    "pax": pax,
                    "company_name": company_name,
                    "rent": f"{rent:,.2f}",
                    "rent_raw": rent,
                })
                s_no += 1

        date_formatted = self.date.strftime("%d/%m/%Y")
        return {
            "date": date_formatted,
            "total_rooms": len(lines),
            "total_pax": total_pax,
            "total_rent": f"{total_rent:,.2f}",
            "lines": lines,
        }

    def get_xlsx_report(self, data, response):
        """Generate XLSX Daily Room Charges Report."""
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {"in_memory": True})
        sheet = workbook.add_worksheet("Daily Room Charges")

        head_format = workbook.add_format({"align": "center", "bold": True, "font_size": 16, "border": 1})
        sub_format = workbook.add_format({"align": "center", "italic": True, "font_size": 10})
        tbl_header = workbook.add_format({"bold": True, "align": "center", "bg_color": "#D3D3D3", "border": 1, "font_size": 10})
        tbl_cell = workbook.add_format({"align": "left", "border": 1, "font_size": 10})
        tbl_center = workbook.add_format({"align": "center", "border": 1, "font_size": 10})
        tbl_num = workbook.add_format({"align": "right", "border": 1, "font_size": 10})
        tbl_total = workbook.add_format({"bold": True, "align": "right", "border": 1, "font_size": 10, "bg_color": "#EAEAEA"})

        chg_data = data.get("charges_data", {})
        sheet.merge_range("A1:H1", "DAILY RENT / ROOM CHARGES REPORT", head_format)
        sheet.merge_range("A2:H2", f"Date: {chg_data.get('date', '-')}", sub_format)

        sheet.set_column("A:A", 6)
        sheet.set_column("B:B", 24)
        sheet.set_column("C:C", 12)
        sheet.set_column("D:D", 14)
        sheet.set_column("E:E", 14)
        sheet.set_column("F:F", 8)
        sheet.set_column("G:G", 24)
        sheet.set_column("H:H", 16)

        row = 4
        headers = ["S No", "Name", "Room No", "Card No", "Check In", "Pax", "Company Name", "Rent"]
        for col_idx, htext in enumerate(headers):
            sheet.write(row, col_idx, htext, tbl_header)

        row += 1
        for item in chg_data.get("lines", []):
            sheet.write(row, 0, item["s_no"], tbl_center)
            sheet.write(row, 1, item["name"], tbl_cell)
            sheet.write(row, 2, item["room_no"], tbl_center)
            sheet.write(row, 3, item["card_no"], tbl_center)
            sheet.write(row, 4, item["check_in"], tbl_center)
            sheet.write(row, 5, item["pax"], tbl_center)
            sheet.write(row, 6, item["company_name"], tbl_cell)
            sheet.write(row, 7, item["rent"], tbl_num)
            row += 1

        # Total Row
        sheet.merge_range(row, 0, row, 6, "Total Daily Rent", tbl_total)
        sheet.write(row, 7, chg_data.get("total_rent", "0.00"), tbl_total)

        workbook.close()
        output.seek(0)
        response.stream.write(output.read())
        output.close()
