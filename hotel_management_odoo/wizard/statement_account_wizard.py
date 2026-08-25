# -*- coding: utf-8 -*-
import io
import json
from datetime import datetime
from odoo import api, fields, models
from odoo.tools import json_default

try:
    from odoo.tools.misc import xlsxwriter
except ImportError:
    import xlsxwriter


class StatementAccountWizard(models.TransientModel):
    """Wizard for generating Statement of Account report per customer / booking."""

    _name = "statement.account.wizard"
    _description = "Statement of Account Wizard"

    partner_id = fields.Many2one("res.partner", string="Customer / Guest", required=True, help="Select customer for Statement of Account")
    booking_id = fields.Many2one("room.booking", string="Booking / Folio", domain="[('partner_id', '=', partner_id)]", help="Optional specific folio")
    date_from = fields.Date(string="From Date")
    date_to = fields.Date(string="To Date")

    def action_print_pdf(self):
        """Generate PDF Statement of Account report."""
        data = {
            "statement": self.generate_statement_data(),
        }
        return self.env.ref("hotel_management_odoo.action_report_statement_account").report_action(self, data=data)

    def action_print_excel(self):
        """Generate Excel Statement of Account report."""
        data = {
            "statement": self.generate_statement_data(),
        }
        return {
            "type": "ir.actions.report",
            "data": {
                "model": "statement.account.wizard",
                "options": json.dumps(data, default=json_default),
                "output_format": "xlsx",
                "report_name": "Statement of Account",
            },
            "report_type": "xlsx",
        }

    def generate_statement_data(self):
        """Build itemized debit/credit statement data with running balance."""
        self.ensure_one()
        domain = [("partner_id", "=", self.partner_id.id)]
        if self.booking_id:
            domain.append(("id", "=", self.booking_id.id))

        bookings = self.env["room.booking"].search(domain, order="checkin_date asc")

        primary_booking = bookings[0] if bookings else False

        card_no = primary_booking.name if primary_booking else (self.booking_id.name if self.booking_id else "-")
        guest_no = self.partner_id.ref or f"GST{self.partner_id.id}"
        guest_name = self.partner_id.name
        nationality = self.partner_id.country_id.name if self.partner_id.country_id else "-"
        company_name = self.partner_id.parent_id.name if self.partner_id.parent_id else (self.partner_id.company_name or "ACCOUNT DIRECT")

        room_no = primary_booking.room_name if (primary_booking and primary_booking.room_name) else (", ".join(primary_booking.room_line_ids.mapped("room_id.name")) if primary_booking else "-")
        checkin_date = primary_booking.checkin_date.strftime("%d/%m/%Y") if (primary_booking and primary_booking.checkin_date) else "-"
        checkin_time = primary_booking.checkin_date.strftime("%I:%M %p").lower() if (primary_booking and primary_booking.checkin_date) else "-"

        raw_lines = []

        for booking in bookings:
            # 1. Room Lines
            for rline in booking.room_line_ids:
                dt = rline.checkin_date or booking.checkin_date
                if self.date_from and dt and dt.date() < self.date_from:
                    continue
                if self.date_to and dt and dt.date() > self.date_to:
                    continue

                raw_lines.append({
                    "date_sort": dt,
                    "date": dt.strftime("%d/%m/%Y") if dt else "-",
                    "description": f"ROOM CHARGES - {rline.room_id.name or 'Room'}",
                    "room_no": rline.room_id.name or booking.room_name or "-",
                    "debit": rline.price_subtotal,
                    "credit": 0.0,
                })
                if rline.price_tax > 0:
                    raw_lines.append({
                        "date_sort": dt,
                        "date": dt.strftime("%d/%m/%Y") if dt else "-",
                        "description": "VAT / TAX",
                        "room_no": rline.room_id.name or booking.room_name or "-",
                        "debit": rline.price_tax,
                        "credit": 0.0,
                    })

            # 2. Food Lines
            for fline in booking.food_order_line_ids:
                dt = booking.checkin_date
                raw_lines.append({
                    "date_sort": dt,
                    "date": dt.strftime("%d/%m/%Y") if dt else "-",
                    "description": f"FOOD ORDER - {fline.food_id.name or 'Food'}",
                    "room_no": booking.room_name or "-",
                    "debit": fline.price_total,
                    "credit": 0.0,
                })

            # 3. Service Lines
            for sline in booking.service_line_ids:
                dt = booking.checkin_date
                raw_lines.append({
                    "date_sort": dt,
                    "date": dt.strftime("%d/%m/%Y") if dt else "-",
                    "description": f"SERVICE - {sline.service_id.name or 'Service'}",
                    "room_no": booking.room_name or "-",
                    "debit": sline.price_total,
                    "credit": 0.0,
                })

            # 4. Fleet Lines
            for vline in booking.vehicle_line_ids:
                dt = booking.checkin_date
                raw_lines.append({
                    "date_sort": dt,
                    "date": dt.strftime("%d/%m/%Y") if dt else "-",
                    "description": f"VEHICLE - {vline.fleet_id.name or 'Vehicle'}",
                    "room_no": booking.room_name or "-",
                    "debit": vline.price_total,
                    "credit": 0.0,
                })

            # 5. Event Lines
            for eline in booking.event_line_ids:
                dt = booking.checkin_date
                raw_lines.append({
                    "date_sort": dt,
                    "date": dt.strftime("%d/%m/%Y") if dt else "-",
                    "description": f"EVENT - {eline.event_id.name or 'Event'}",
                    "room_no": booking.room_name or "-",
                    "debit": eline.price_total,
                    "credit": 0.0,
                })

            # 6. POS Orders
            for pos_link in booking.pos_order_line_ids:
                pos = pos_link.pos_order_id
                dt = pos.date_order or booking.checkin_date
                raw_lines.append({
                    "date_sort": dt,
                    "date": dt.strftime("%d/%m/%Y") if dt else "-",
                    "description": f"RESTAURANT CHARGE ({pos.pos_reference or pos.name})",
                    "room_no": booking.room_name or "-",
                    "debit": pos.amount_total,
                    "credit": 0.0,
                })

            # 7. Payments / Invoices
            if booking.hotel_invoice_id:
                inv = booking.hotel_invoice_id
                paid_amt = inv.amount_total - inv.amount_residual
                if paid_amt > 0:
                    raw_lines.append({
                        "date_sort": booking.checkout_date or booking.checkin_date,
                        "date": (booking.checkout_date or booking.checkin_date).strftime("%d/%m/%Y"),
                        "description": "PAYMENT RECEIVED",
                        "room_no": booking.room_name or "-",
                        "debit": 0.0,
                        "credit": paid_amt,
                    })

        raw_lines.sort(key=lambda x: x["date_sort"] or datetime.min)

        lines = []
        running_balance = 0.0
        s_no = 1
        for item in raw_lines:
            debit = item["debit"]
            credit = item["credit"]
            running_balance += (debit - credit)
            lines.append({
                "s_no": s_no,
                "date": item["date"],
                "description": item["description"],
                "room_no": item["room_no"],
                "debit": f"{debit:,.2f}" if debit else "0.00",
                "credit": f"{credit:,.2f}" if credit else "-",
                "balance": f"{running_balance:,.2f}",
                "debit_raw": debit,
                "credit_raw": credit,
                "balance_raw": running_balance,
            })
            s_no += 1

        return {
            "header": {
                "card_no": card_no,
                "guest_no": guest_no,
                "name": guest_name,
                "nationality": nationality,
                "company": company_name,
                "room_no": room_no,
                "pax": "1",
                "arrival_date": checkin_date,
                "arrival_time": checkin_time,
                "balance_amount": f"{running_balance:,.2f}",
            },
            "lines": lines,
        }

    def get_xlsx_report(self, data, response):
        """Organizing xlsx Statement of Account report"""
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {"in_memory": True})
        sheet = workbook.add_worksheet("Statement of Account")

        head_format = workbook.add_format({"align": "center", "bold": True, "font_size": 18, "border": 1})
        label_bold = workbook.add_format({"bold": True, "font_size": 11})
        val_norm = workbook.add_format({"font_size": 11})
        tbl_header = workbook.add_format({"bold": True, "align": "center", "bg_color": "#D3D3D3", "border": 1, "font_size": 11})
        tbl_cell = workbook.add_format({"align": "left", "border": 1, "font_size": 10})
        tbl_num = workbook.add_format({"align": "right", "border": 1, "font_size": 10})

        stmt = data["statement"]
        hdr = stmt["header"]

        sheet.merge_range("A1:G1", "STATEMENT OF ACCOUNT", head_format)
        sheet.set_column("A:G", 18)

        sheet.write("A3", "Card No:", label_bold)
        sheet.write("B3", hdr["card_no"], val_norm)
        sheet.write("E3", "Room No:", label_bold)
        sheet.write("F3", hdr["room_no"], val_norm)

        sheet.write("A4", "Guest No:", label_bold)
        sheet.write("B4", hdr["guest_no"], val_norm)
        sheet.write("E4", "No of Pax:", label_bold)
        sheet.write("F4", hdr["pax"], val_norm)

        sheet.write("A5", "Name:", label_bold)
        sheet.write("B5", hdr["name"], val_norm)
        sheet.write("E5", "Arrival Date:", label_bold)
        sheet.write("F5", hdr["arrival_date"], val_norm)

        sheet.write("A6", "Nationality:", label_bold)
        sheet.write("B6", hdr["nationality"], val_norm)
        sheet.write("E6", "Arrival Time:", label_bold)
        sheet.write("F6", hdr["arrival_time"], val_norm)

        sheet.write("A7", "Company:", label_bold)
        sheet.write("B7", hdr["company"], val_norm)
        sheet.write("E7", "Balance Amount:", label_bold)
        sheet.write("F7", hdr["balance_amount"], label_bold)

        row = 9
        headers = ["S No", "Date", "Description", "Room No", "Debit", "Credit", "Balance"]
        for col_idx, htext in enumerate(headers):
            sheet.write(row, col_idx, htext, tbl_header)

        row += 1
        for item in stmt["lines"]:
            sheet.write(row, 0, item["s_no"], tbl_cell)
            sheet.write(row, 1, item["date"], tbl_cell)
            sheet.write(row, 2, item["description"], tbl_cell)
            sheet.write(row, 3, item["room_no"], tbl_cell)
            sheet.write(row, 4, item["debit"], tbl_num)
            sheet.write(row, 5, item["credit"], tbl_num)
            sheet.write(row, 6, item["balance"], tbl_num)
            row += 1

        workbook.close()
        output.seek(0)
        response.stream.write(output.read())
        output.close()
