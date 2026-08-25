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


class DailyCashReportWizard(models.TransientModel):
    """Wizard for generating Cash Report / Daily Collections & POS Transactions."""

    _name = "daily.cash.report.wizard"
    _description = "Daily Cash & POS Report Wizard"

    date_from = fields.Date(string="From Date", default=fields.Date.context_today, required=True, help="Start date for cash transactions")
    date_to = fields.Date(string="To Date", default=fields.Date.context_today, required=True, help="End date for cash transactions")
    journal_id = fields.Many2one("account.journal", string="Payment Journal / Method", help="Optional filter by journal (Cash, Bank, etc.)")

    def action_print_pdf(self):
        """Generate PDF Cash Report / Daily Collections."""
        data = {
            "cash_data": self.generate_data(),
        }
        return self.env.ref("hotel_management_odoo.action_report_daily_cash").report_action(self, data=data)

    def action_print_excel(self):
        """Generate Excel Cash Report / Daily Collections."""
        data = {
            "cash_data": self.generate_data(),
        }
        return {
            "type": "ir.actions.report",
            "data": {
                "model": "daily.cash.report.wizard",
                "options": json.dumps(data, default=json_default),
                "output_format": "xlsx",
                "report_name": "Daily Cash and POS Report",
            },
            "report_type": "xlsx",
        }

    def generate_data(self):
        """Aggregate daily POS transactions, restaurant orders, and hotel reception collections."""
        self.ensure_one()
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValidationError("From Date must be less than or equal to To Date.")

        dt_start = datetime.combine(self.date_from, time.min)
        dt_end = datetime.combine(self.date_to, time.max)

        raw_records = []
        method_totals = {}

        # 1. POS Payments & Orders
        if "pos.payment" in self.env:
            pos_domain = [
                ("payment_date", ">=", dt_start),
                ("payment_date", "<=", dt_end),
            ]
            pos_payments = self.env["pos.payment"].search(pos_domain, order="payment_date asc")
            for pp in pos_payments:
                order = pp.pos_order_id
                dt = pp.payment_date or order.date_order
                m_name = pp.payment_method_id.name if pp.payment_method_id else "Cash"
                code = "CAS" if "cash" in m_name.lower() else m_name.upper()[:8]

                partner_name = order.partner_id.name if order.partner_id else (order.booking_id.partner_id.name if order.booking_id else "Walk-in Guest")
                voucher_no = order.pos_reference or order.name or "-"
                remarks = f"POS - {order.session_id.name if order.session_id else 'Restaurant'}"
                card_no = order.booking_id.name if order.booking_id else "-"
                room_no = order.booking_id.room_name or "-"

                amount = pp.amount
                credit = amount if amount >= 0 else 0.0
                debit = abs(amount) if amount < 0 else 0.0

                method_totals[m_name] = method_totals.get(m_name, 0.0) + credit

                raw_records.append({
                    "dt": dt,
                    "date": dt.strftime("%d/%m/%Y %I:%M %p") if dt else "-",
                    "cas": code,
                    "method": m_name,
                    "name": partner_name,
                    "voucher_no": voucher_no,
                    "remarks": remarks,
                    "card_no": card_no,
                    "room_no": room_no,
                    "debit": debit,
                    "credit": credit,
                })

        # 2. Hotel Folio Account Payments (e.g. from invoices or account moves registered on bookings)
        if "account.payment" in self.env:
            acc_domain = [
                ("date", ">=", self.date_from),
                ("date", "<=", self.date_to),
                ("state", "in", ["posted", "paid"]),
            ]
            if self.journal_id:
                acc_domain.append(("journal_id", "=", self.journal_id.id))

            payments = self.env["account.payment"].search(acc_domain, order="date asc")
            for pay in payments:
                j_name = pay.journal_id.name if pay.journal_id else "Bank/Cash"
                code = "CAS" if "cash" in j_name.lower() else j_name.upper()[:8]
                dt = datetime.combine(pay.date, time.min) if pay.date else False

                # Check linked booking
                booking = self.env["room.booking"].search([
                    "|", ("hotel_invoice_id.payment_ids", "in", [pay.id]),
                    ("partner_id", "=", pay.partner_id.id)
                ], limit=1)

                card_no = booking.name if booking else "-"
                room_no = booking.room_name if booking else "-"

                amt = pay.amount
                credit = amt if pay.payment_type == "inbound" else 0.0
                debit = amt if pay.payment_type == "outbound" else 0.0

                method_totals[j_name] = method_totals.get(j_name, 0.0) + credit

                raw_records.append({
                    "dt": dt or datetime.min,
                    "date": pay.date.strftime("%d/%m/%Y") if pay.date else "-",
                    "cas": code,
                    "method": j_name,
                    "name": pay.partner_id.name or "-",
                    "voucher_no": pay.name or "-",
                    "remarks": pay.ref or "Hotel Collection / Bill Payment",
                    "card_no": card_no,
                    "room_no": room_no,
                    "debit": debit,
                    "credit": credit,
                })

        # Sort chronologically
        raw_records.sort(key=lambda x: x["dt"] or datetime.min)

        lines = []
        running_balance = 0.0
        total_debit = 0.0
        total_credit = 0.0
        s_no = 1

        for r in raw_records:
            debit = r["debit"]
            credit = r["credit"]
            running_balance += (credit - debit)
            total_debit += debit
            total_credit += credit

            lines.append({
                "s_no": s_no,
                "date": r["date"],
                "cas": r["cas"],
                "name": r["name"],
                "voucher_no": r["voucher_no"],
                "remarks": r["remarks"],
                "card_no": r["card_no"],
                "room_no": r["room_no"],
                "debit": f"{debit:,.2f}" if debit else "-",
                "credit": f"{credit:,.2f}" if credit else "-",
                "balance": f"{running_balance:,.2f}",
            })
            s_no += 1

        method_summary = [{"method": k, "total": f"{v:,.2f}"} for k, v in sorted(method_totals.items())]

        period_str = f"{self.date_from.strftime('%d/%m/%Y')} to {self.date_to.strftime('%d/%m/%Y')}"
        return {
            "period": period_str,
            "total_records": len(lines),
            "total_debit": f"{total_debit:,.2f}",
            "total_credit": f"{total_credit:,.2f}",
            "closing_balance": f"{running_balance:,.2f}",
            "method_summary": method_summary,
            "lines": lines,
        }

    def get_xlsx_report(self, data, response):
        """Generate XLSX Daily Cash and POS Report."""
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {"in_memory": True})
        sheet = workbook.add_worksheet("Daily Cash Report")

        head_format = workbook.add_format({"align": "center", "bold": True, "font_size": 16, "border": 1})
        sub_format = workbook.add_format({"align": "center", "italic": True, "font_size": 10})
        tbl_header = workbook.add_format({"bold": True, "align": "center", "bg_color": "#D3D3D3", "border": 1, "font_size": 10})
        tbl_cell = workbook.add_format({"align": "left", "border": 1, "font_size": 10})
        tbl_center = workbook.add_format({"align": "center", "border": 1, "font_size": 10})
        tbl_num = workbook.add_format({"align": "right", "border": 1, "font_size": 10})
        tbl_total = workbook.add_format({"bold": True, "align": "right", "border": 1, "font_size": 10, "bg_color": "#EAEAEA"})

        c_data = data.get("cash_data", {})
        sheet.merge_range("A1:K1", "CASH REPORT / DAILY COLLECTIONS & POS TRANSACTIONS", head_format)
        sheet.merge_range("A2:K2", f"Period: {c_data.get('period', '-')}", sub_format)

        sheet.set_column("A:A", 6)
        sheet.set_column("B:B", 18)
        sheet.set_column("C:C", 10)
        sheet.set_column("D:D", 20)
        sheet.set_column("E:E", 16)
        sheet.set_column("F:F", 22)
        sheet.set_column("G:G", 12)
        sheet.set_column("H:H", 10)
        sheet.set_column("I:I", 12)
        sheet.set_column("J:J", 12)
        sheet.set_column("K:K", 14)

        row = 4
        headers = ["S.No", "Date", "CAS", "Name", "Voucher No", "Remarks", "CardNo", "RoomNo", "Debit", "Credit", "Balance"]
        for col_idx, htext in enumerate(headers):
            sheet.write(row, col_idx, htext, tbl_header)

        row += 1
        for item in c_data.get("lines", []):
            sheet.write(row, 0, item["s_no"], tbl_center)
            sheet.write(row, 1, item["date"], tbl_center)
            sheet.write(row, 2, item["cas"], tbl_center)
            sheet.write(row, 3, item["name"], tbl_cell)
            sheet.write(row, 4, item["voucher_no"], tbl_center)
            sheet.write(row, 5, item["remarks"], tbl_cell)
            sheet.write(row, 6, item["card_no"], tbl_center)
            sheet.write(row, 7, item["room_no"], tbl_center)
            sheet.write(row, 8, item["debit"], tbl_num)
            sheet.write(row, 9, item["credit"], tbl_num)
            sheet.write(row, 10, item["balance"], tbl_num)
            row += 1

        # Total Row
        sheet.merge_range(row, 0, row, 7, "Total / Closing Balance", tbl_total)
        sheet.write(row, 8, c_data.get("total_debit", "0.00"), tbl_total)
        sheet.write(row, 9, c_data.get("total_credit", "0.00"), tbl_total)
        sheet.write(row, 10, c_data.get("closing_balance", "0.00"), tbl_total)

        workbook.close()
        output.seek(0)
        response.stream.write(output.read())
        output.close()
