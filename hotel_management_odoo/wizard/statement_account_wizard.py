# -*- coding: utf-8 -*-
import io
import json
from datetime import datetime, timedelta
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
        """Build itemized day-by-day debit/credit statement data with categorized summary."""
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
            # 1. Room Lines (Broken down day-by-day for each night stayed)
            for rline in booking.room_line_ids:
                r_in = rline.checkin_date or booking.checkin_date
                duration = int(rline.uom_qty or 1)
                if duration <= 0:
                    duration = 1

                daily_rent = (rline.price_subtotal / duration) if duration else rline.price_subtotal
                daily_tax = (rline.price_tax / duration) if (rline.price_tax and duration) else 0.0

                for d in range(duration):
                    dt = (r_in + timedelta(days=d)) if r_in else False
                    if self.date_from and dt and dt.date() < self.date_from:
                        continue
                    if self.date_to and dt and dt.date() > self.date_to:
                        continue

                    raw_lines.append({
                        "date_sort": dt,
                        "date": dt.strftime("%d/%m/%Y") if dt else "-",
                        "description": f"ROOM CHARGE - {rline.room_id.name or 'Room'}" if duration == 1 else f"ROOM CHARGE - {rline.room_id.name or 'Room'} (Night {d+1})",
                        "room_no": rline.room_id.name or booking.room_name or "-",
                        "category": "room",
                        "debit": daily_rent,
                        "credit": 0.0,
                    })
                    if daily_tax > 0:
                        raw_lines.append({
                            "date_sort": dt,
                            "date": dt.strftime("%d/%m/%Y") if dt else "-",
                            "description": "VAT / TAX",
                            "room_no": rline.room_id.name or booking.room_name or "-",
                            "category": "tax",
                            "debit": daily_tax,
                            "credit": 0.0,
                        })

            # 2. Food Lines
            for fline in booking.food_order_line_ids:
                dt = booking.checkin_date
                if self.date_from and dt and dt.date() < self.date_from:
                    continue
                if self.date_to and dt and dt.date() > self.date_to:
                    continue
                raw_lines.append({
                    "date_sort": dt,
                    "date": dt.strftime("%d/%m/%Y") if dt else "-",
                    "description": f"FOOD ORDER - {fline.food_id.name or 'Food'}",
                    "room_no": booking.room_name or "-",
                    "category": "restaurant",
                    "debit": fline.price_total,
                    "credit": 0.0,
                })

            # 3. Service Lines
            for sline in booking.service_line_ids:
                dt = booking.checkin_date
                if self.date_from and dt and dt.date() < self.date_from:
                    continue
                if self.date_to and dt and dt.date() > self.date_to:
                    continue
                raw_lines.append({
                    "date_sort": dt,
                    "date": dt.strftime("%d/%m/%Y") if dt else "-",
                    "description": f"SERVICE - {sline.service_id.name or 'Service'}",
                    "room_no": booking.room_name or "-",
                    "category": "service",
                    "debit": sline.price_total,
                    "credit": 0.0,
                })

            # 4. Fleet Lines
            for vline in booking.vehicle_line_ids:
                dt = booking.checkin_date
                if self.date_from and dt and dt.date() < self.date_from:
                    continue
                if self.date_to and dt and dt.date() > self.date_to:
                    continue
                raw_lines.append({
                    "date_sort": dt,
                    "date": dt.strftime("%d/%m/%Y") if dt else "-",
                    "description": f"VEHICLE - {vline.fleet_id.name or 'Vehicle'}",
                    "room_no": booking.room_name or "-",
                    "category": "fleet",
                    "debit": vline.price_total,
                    "credit": 0.0,
                })

            # 5. Event Lines
            for eline in booking.event_line_ids:
                dt = booking.checkin_date
                if self.date_from and dt and dt.date() < self.date_from:
                    continue
                if self.date_to and dt and dt.date() > self.date_to:
                    continue
                raw_lines.append({
                    "date_sort": dt,
                    "date": dt.strftime("%d/%m/%Y") if dt else "-",
                    "description": f"EVENT - {eline.event_id.name or 'Event'}",
                    "room_no": booking.room_name or "-",
                    "category": "event",
                    "debit": eline.price_total,
                    "credit": 0.0,
                })

            # 6. POS Orders
            for pos_link in booking.pos_order_line_ids:
                pos = pos_link.pos_order_id
                dt = pos.date_order or booking.checkin_date
                if self.date_from and dt and dt.date() < self.date_from:
                    continue
                if self.date_to and dt and dt.date() > self.date_to:
                    continue
                raw_lines.append({
                    "date_sort": dt,
                    "date": dt.strftime("%d/%m/%Y") if dt else "-",
                    "description": f"RESTAURANT CHARGE ({pos.pos_reference or pos.name})",
                    "room_no": booking.room_name or "-",
                    "category": "restaurant",
                    "debit": pos.amount_total,
                    "credit": 0.0,
                })

            # 7. Payments / Invoices
            if booking.hotel_invoice_id:
                inv = booking.hotel_invoice_id
                paid_amt = inv.amount_total - inv.amount_residual
                if paid_amt > 0:
                    dt = booking.checkout_date or booking.checkin_date
                    raw_lines.append({
                        "date_sort": dt,
                        "date": dt.strftime("%d/%m/%Y") if dt else "-",
                        "description": "PAYMENT RECEIVED",
                        "room_no": booking.room_name or "-",
                        "category": "payment",
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

        # Summary Category Totals
        total_room = sum(x["debit"] for x in raw_lines if x.get("category") == "room")
        total_tax = sum(x["debit"] for x in raw_lines if x.get("category") == "tax")
        total_restaurant = sum(x["debit"] for x in raw_lines if x.get("category") == "restaurant")
        total_service = sum(x["debit"] for x in raw_lines if x.get("category") == "service")
        total_fleet = sum(x["debit"] for x in raw_lines if x.get("category") == "fleet")
        total_event = sum(x["debit"] for x in raw_lines if x.get("category") == "event")
        total_payments = sum(x["credit"] for x in raw_lines if x.get("category") == "payment")
        total_debit = sum(x["debit"] for x in raw_lines)
        total_credit = sum(x["credit"] for x in raw_lines)

        summary = {
            "total_room": f"{total_room:,.2f}",
            "total_tax": f"{total_tax:,.2f}",
            "total_restaurant": f"{total_restaurant:,.2f}",
            "total_service": f"{total_service:,.2f}",
            "total_fleet": f"{total_fleet:,.2f}",
            "total_event": f"{total_event:,.2f}",
            "total_payments": f"{total_payments:,.2f}",
            "total_debit": f"{total_debit:,.2f}",
            "total_credit": f"{total_credit:,.2f}",
            "net_balance": f"{running_balance:,.2f}",
        }

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
            "summary": summary,
        }

    def get_xlsx_report(self, data, response):
        """Organizing xlsx Statement of Account report"""
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {"in_memory": True})
        sheet = workbook.add_worksheet("Statement of Account")

        head_format = workbook.add_format({"align": "center", "bold": True, "font_size": 16, "border": 1, "bg_color": "#2c3e50", "font_color": "#ffffff"})
        label_bold = workbook.add_format({"bold": True, "font_size": 10})
        val_norm = workbook.add_format({"font_size": 10})
        tbl_header = workbook.add_format({"bold": True, "align": "center", "bg_color": "#4A6572", "font_color": "#ffffff", "border": 1, "font_size": 10})
        tbl_cell = workbook.add_format({"align": "left", "border": 1, "font_size": 9})
        tbl_cell_center = workbook.add_format({"align": "center", "border": 1, "font_size": 9})
        tbl_num = workbook.add_format({"align": "right", "border": 1, "font_size": 9})
        sum_header = workbook.add_format({"bold": True, "align": "left", "bg_color": "#f2f2f2", "border": 1, "font_size": 10})
        sum_val = workbook.add_format({"bold": True, "align": "right", "border": 1, "font_size": 10})

        stmt = data["statement"]
        hdr = stmt["header"]
        summary = stmt.get("summary", {})

        sheet.merge_range("A1:G1", "STATEMENT OF ACCOUNT", head_format)
        sheet.set_column("A:A", 8)
        sheet.set_column("B:B", 14)
        sheet.set_column("C:C", 35)
        sheet.set_column("D:D", 14)
        sheet.set_column("E:G", 15)

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
            sheet.write(row, 0, item["s_no"], tbl_cell_center)
            sheet.write(row, 1, item["date"], tbl_cell_center)
            sheet.write(row, 2, item["description"], tbl_cell)
            sheet.write(row, 3, item["room_no"], tbl_cell_center)
            sheet.write(row, 4, item["debit"], tbl_num)
            sheet.write(row, 5, item["credit"], tbl_num)
            sheet.write(row, 6, item["balance"], tbl_num)
            row += 1

        # Summary Section at Bottom
        row += 2
        sheet.merge_range(row, 0, row, 3, "SUMMARY BREAKDOWN", sum_header)
        sheet.merge_range(row, 4, row, 6, "STATEMENT TOTALS", sum_header)

        row += 1
        sheet.write(row, 0, "Total Room Charges", tbl_cell)
        sheet.write(row, 3, summary.get("total_room", "0.00"), tbl_num)
        sheet.write(row, 4, "Total Charges (Debit)", tbl_cell)
        sheet.write(row, 6, summary.get("total_debit", "0.00"), sum_val)

        row += 1
        sheet.write(row, 0, "Total VAT / Tax", tbl_cell)
        sheet.write(row, 3, summary.get("total_tax", "0.00"), tbl_num)
        sheet.write(row, 4, "Total Payments (Credit)", tbl_cell)
        sheet.write(row, 6, summary.get("total_payments", "0.00"), sum_val)

        row += 1
        sheet.write(row, 0, "Total Restaurant / Food / POS", tbl_cell)
        sheet.write(row, 3, summary.get("total_restaurant", "0.00"), tbl_num)
        sheet.write(row, 4, "NET BALANCE DUE", sum_header)
        sheet.write(row, 6, summary.get("net_balance", "0.00"), sum_val)

        row += 1
        sheet.write(row, 0, "Total Hotel Services & Fleet", tbl_cell)
        sheet.write(row, 3, summary.get("total_service", "0.00"), tbl_num)

        workbook.close()
        output.seek(0)
        response.stream.write(output.read())
        output.close()
