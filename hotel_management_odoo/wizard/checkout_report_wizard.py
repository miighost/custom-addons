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
from odoo.exceptions import ValidationError
from odoo.tools import json_default

try:
    from odoo.tools.misc import xlsxwriter
except ImportError:
    import xlsxwriter


class CheckoutReportWizard(models.TransientModel):
    """Wizard for generating Check Out Report."""

    _name = "checkout.report.wizard"
    _description = "Check Out Report Wizard"

    date_from = fields.Date(string="Check Out From Date", help="Start of check-out date range")
    date_to = fields.Date(string="Check Out To Date", help="End of check-out date range")
    partner_id = fields.Many2one("res.partner", string="Guest / Company", help="Filter by guest or company")
    room_id = fields.Many2one("hotel.room", string="Room", help="Filter by specific room")

    def action_print_pdf(self):
        """Generate PDF Check Out Report."""
        data = {
            "checkout_data": self.generate_data(),
        }
        return self.env.ref("hotel_management_odoo.action_report_checkout").report_action(self, data=data)

    def action_print_excel(self):
        """Generate Excel Check Out Report."""
        data = {
            "checkout_data": self.generate_data(),
        }
        return {
            "type": "ir.actions.report",
            "data": {
                "model": "checkout.report.wizard",
                "options": json.dumps(data, default=json_default),
                "output_format": "xlsx",
                "report_name": "Check Out Report",
            },
            "report_type": "xlsx",
        }

    def generate_data(self):
        """Fetch and structure check out records matching the criteria."""
        self.ensure_one()
        domain = []
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValidationError("From Date must be less than or equal to To Date.")

        if self.date_from:
            dt_from = datetime.combine(self.date_from, time.min)
            domain.append(("checkout_date", ">=", dt_from))
        if self.date_to:
            dt_to = datetime.combine(self.date_to, time.max)
            domain.append(("checkout_date", "<=", dt_to))

        if self.partner_id:
            domain.append(("partner_id", "=", self.partner_id.id))

        bookings = self.env["room.booking"].search(domain, order="checkout_date asc")
        if self.room_id:
            bookings = bookings.filtered(lambda b: self.room_id.id in b.room_line_ids.mapped("room_id.id"))

        lines = []
        s_no = 1
        total_rate = 0.0

        for b in bookings:
            room_names = b.room_name or ", ".join(b.room_line_ids.mapped("room_id.name")) or "-"
            pax = sum(line.room_id.num_person for line in b.room_line_ids if line.room_id) or 1
            invoice_no = b.hotel_invoice_id.name if b.hotel_invoice_id else "-"
            company_name = b.partner_id.parent_id.name if b.partner_id.parent_id else (b.partner_id.company_name or "ACCOUNT DIRECT")
            rate = sum(b.room_line_ids.mapped("price_total"))
            total_rate += rate

            in_date_str = b.checkin_date.strftime("%d/%m/%Y") if b.checkin_date else "-"
            in_time_str = b.checkin_date.strftime("%I:%M %p") if b.checkin_date else "-"
            out_date_str = b.checkout_date.strftime("%d/%m/%Y") if b.checkout_date else "-"
            out_time_str = b.checkout_date.strftime("%I:%M %p") if b.checkout_date else "-"

            lines.append({
                "s_no": s_no,
                "guest_name": b.partner_id.name or "-",
                "room_no": room_names,
                "pax": pax,
                "invoice_no": invoice_no,
                "company": company_name,
                "rate": f"{rate:,.2f}",
                "rate_raw": rate,
                "in_date": in_date_str,
                "in_time": in_time_str,
                "out_date": out_date_str,
                "out_time": out_time_str,
                "booking_no": b.name or "-",
            })
            s_no += 1

        filter_period = "All Check-Outs"
        if self.date_from and self.date_to:
            filter_period = f"{self.date_from.strftime('%d/%m/%Y')} to {self.date_to.strftime('%d/%m/%Y')}"
        elif self.date_from:
            filter_period = f"From {self.date_from.strftime('%d/%m/%Y')}"
        elif self.date_to:
            filter_period = f"Up to {self.date_to.strftime('%d/%m/%Y')}"

        return {
            "period": filter_period,
            "total_records": len(lines),
            "total_rate": f"{total_rate:,.2f}",
            "lines": lines,
        }

    def get_xlsx_report(self, data, response):
        """Generate XLSX Check Out Report."""
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {"in_memory": True})
        sheet = workbook.add_worksheet("Check Out Report")

        head_format = workbook.add_format({"align": "center", "bold": True, "font_size": 16, "border": 1})
        sub_format = workbook.add_format({"align": "center", "italic": True, "font_size": 10})
        tbl_header = workbook.add_format({"bold": True, "align": "center", "bg_color": "#D3D3D3", "border": 1, "font_size": 10})
        tbl_cell = workbook.add_format({"align": "left", "border": 1, "font_size": 10})
        tbl_center = workbook.add_format({"align": "center", "border": 1, "font_size": 10})
        tbl_num = workbook.add_format({"align": "right", "border": 1, "font_size": 10})
        tbl_total = workbook.add_format({"bold": True, "align": "right", "border": 1, "font_size": 10, "bg_color": "#EAEAEA"})

        chk_data = data.get("checkout_data", {})
        sheet.merge_range("A1:K1", "CHECK OUT REPORT", head_format)
        sheet.merge_range("A2:K2", f"Period: {chk_data.get('period', '-')}", sub_format)

        sheet.set_column("A:A", 6)
        sheet.set_column("B:B", 22)
        sheet.set_column("C:C", 12)
        sheet.set_column("D:D", 6)
        sheet.set_column("E:E", 16)
        sheet.set_column("F:F", 20)
        sheet.set_column("G:G", 14)
        sheet.set_column("H:H", 12)
        sheet.set_column("I:I", 10)
        sheet.set_column("J:J", 12)
        sheet.set_column("K:K", 10)

        row = 4
        headers = ["S No", "Guest Name", "Room No", "Pax", "Invoice No", "Company", "Rate", "In Date", "In Time", "Out Date", "Out Time"]
        for col_idx, htext in enumerate(headers):
            sheet.write(row, col_idx, htext, tbl_header)

        row += 1
        for item in chk_data.get("lines", []):
            sheet.write(row, 0, item["s_no"], tbl_center)
            sheet.write(row, 1, item["guest_name"], tbl_cell)
            sheet.write(row, 2, item["room_no"], tbl_center)
            sheet.write(row, 3, item["pax"], tbl_center)
            sheet.write(row, 4, item["invoice_no"], tbl_center)
            sheet.write(row, 5, item["company"], tbl_cell)
            sheet.write(row, 6, item["rate"], tbl_num)
            sheet.write(row, 7, item["in_date"], tbl_center)
            sheet.write(row, 8, item["in_time"], tbl_center)
            sheet.write(row, 9, item["out_date"], tbl_center)
            sheet.write(row, 10, item["out_time"], tbl_center)
            row += 1

        # Total Row
        sheet.merge_range(row, 0, row, 5, "Total Rate", tbl_total)
        sheet.write(row, 6, chk_data.get("total_rate", "0.00"), tbl_total)
        sheet.merge_range(row, 7, row, 10, "", tbl_total)

        workbook.close()
        output.seek(0)
        response.stream.write(output.read())
        output.close()
