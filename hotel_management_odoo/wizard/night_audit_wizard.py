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
from odoo import api, fields, models
from odoo.tools import json_default

try:
    from odoo.tools.misc import xlsxwriter
except ImportError:
    import xlsxwriter


class NightAuditWizard(models.TransientModel):
    """Wizard for generating Consolidated 24-Hour Night Audit Pack (5-in-1 Report)."""

    _name = "night.audit.wizard"
    _description = "Night Audit Pack Wizard"

    date = fields.Date(
        string="Audit Date",
        default=fields.Date.context_today,
        required=True,
        help="Select the 24-hour audit date"
    )
    user_id = fields.Many2one(
        "res.users",
        string="Audited By",
        default=lambda self: self.env.user,
        required=True,
        help="Auditor or receptionist conducting the night audit"
    )
    notes = fields.Text(string="Audit Remarks / Notes")

    def action_print_pdf(self):
        """Generate Consolidated PDF Night Audit Pack."""
        data = {
            "audit_data": self.generate_night_audit_data(),
        }
        return self.env.ref("hotel_management_odoo.action_report_night_audit").report_action(self, data=data)

    def action_print_excel(self):
        """Generate Consolidated Multi-Tab Excel Night Audit Pack."""
        data = {
            "audit_data": self.generate_night_audit_data(),
        }
        return {
            "type": "ir.actions.report",
            "data": {
                "model": "night.audit.wizard",
                "options": json.dumps(data, default=json_default),
                "output_format": "xlsx",
                "report_name": f"Night Audit Pack - {self.date.strftime('%d-%b-%Y')}",
            },
            "report_type": "xlsx",
        }

    def generate_night_audit_data(self):
        """Consolidate 24-hr Operational & Financial Audit Data into a unified dataset."""
        self.ensure_one()
        audit_date = self.date
        dt_start = datetime.combine(audit_date, time.min)
        dt_end = datetime.combine(audit_date, time.max)

        # -------------------------------------------------------------
        # 1. ROOM ANALYSIS & OCCUPANCY KPIS
        # -------------------------------------------------------------
        all_rooms = self.env["hotel.room"].search([])
        total_rooms = len(all_rooms)

        maint_requests = self.env["maintenance.request"].search([
            ("type", "=", "room"),
            ("state", "in", ["draft", "assign", "ongoing", "support"])
        ])
        maintenance_count = len(set(maint_requests.mapped("room_maintenance_ids.id")))

        cleaning_requests = self.env["cleaning.request"].search([
            ("cleaning_type", "=", "room"),
            ("state", "in", ["draft", "assign", "ongoing", "support"])
        ])
        cleaning_count = len(set(cleaning_requests.mapped("room_id.id")))

        available_rooms_count = max(0, total_rooms - maintenance_count)

        active_bookings = self.env["room.booking"].search([
            ("checkin_date", "<=", dt_end),
            ("checkout_date", ">=", dt_start),
            ("state", "in", ["check_in", "reserved", "check_out", "done"]),
        ])

        occupied_room_ids = set()
        inhouse_pax = 0
        total_room_rent = 0.0

        for b in active_bookings:
            for rline in b.room_line_ids:
                r_in = rline.checkin_date or b.checkin_date
                r_out = rline.checkout_date or b.checkout_date
                if r_in and r_in > dt_end:
                    continue
                if r_out and r_out < dt_start:
                    continue

                if rline.room_id:
                    occupied_room_ids.add(rline.room_id.id)

                pax = rline.room_id.num_person if (rline.room_id and rline.room_id.num_person) else 1
                inhouse_pax += pax
                rent = rline.price_unit if rline.price_unit else (rline.price_subtotal / (b.duration or 1) if b.duration else rline.price_subtotal)
                total_room_rent += rent

        occupied_count = len(occupied_room_ids)
        vacant_count = max(0, available_rooms_count - occupied_count)
        occupancy_rate = (occupied_count / available_rooms_count * 100.0) if available_rooms_count > 0 else 0.0

        arr = (total_room_rent / occupied_count) if occupied_count > 0 else 0.0
        revpar = (total_room_rent / available_rooms_count) if available_rooms_count > 0 else 0.0
        agr = (total_room_rent / inhouse_pax) if inhouse_pax > 0 else 0.0

        total_restaurant_pos = 0.0
        if "pos.order" in self.env:
            pos_orders = self.env["pos.order"].search([
                ("date_order", ">=", dt_start),
                ("date_order", "<=", dt_end),
                ("state", "in", ["paid", "done", "invoiced"]),
            ])
            total_restaurant_pos += sum(pos_orders.mapped("amount_total"))

        food_lines = self.env["food.booking.line"].search([
            ("booking_id.checkin_date", "<=", dt_end),
            ("booking_id.checkout_date", ">=", dt_start),
        ])
        total_restaurant_pos += sum(food_lines.mapped("price_total"))
        grand_total_revenue = total_room_rent + total_restaurant_pos

        # -------------------------------------------------------------
        # 2. IN-HOUSE GUEST LIST
        # -------------------------------------------------------------
        inhouse_bookings = self.env["room.booking"].search([
            ("state", "=", "check_in"),
        ], order="name asc")

        inhouse_list = []
        i_idx = 1
        for ih in inhouse_bookings:
            room_names = ih.room_name or ", ".join(ih.room_line_ids.mapped("room_id.name")) or "-"
            rate = sum(ih.room_line_ids.mapped("price_total"))
            cin_str = ih.checkin_date.strftime("%d/%m/%Y") if ih.checkin_date else "-"
            cout_str = ih.checkout_date.strftime("%d/%m/%Y") if ih.checkout_date else "-"
            inhouse_list.append({
                "s_no": i_idx,
                "guest_name": ih.partner_id.name or "-",
                "room_no": room_names,
                "checkin": cin_str,
                "checkout": cout_str,
                "pricelist": ih.pricelist_id.name if ih.pricelist_id else "-",
                "nationality": ih.partner_id.country_id.name if ih.partner_id.country_id else "-",
                "company": ih.partner_id.parent_id.name if ih.partner_id.parent_id else (ih.partner_id.company_name or "-"),
                "room_rate": f"{rate:,.2f}",
            })
            i_idx += 1

        # -------------------------------------------------------------
        # 3. CHECK-INS (ARRIVALS) & CHECK-OUTS (DEPARTURES)
        # -------------------------------------------------------------
        arrivals_records = self.env["room.booking"].search([
            ("checkin_date", ">=", dt_start),
            ("checkin_date", "<=", dt_end),
            ("state", "in", ["check_in", "reserved", "check_out", "done"]),
        ], order="checkin_date asc")

        arrivals_list = []
        a_idx = 1
        for arr_rec in arrivals_records:
            arrivals_list.append({
                "s_no": a_idx,
                "guest_name": arr_rec.partner_id.name or "-",
                "room_no": arr_rec.room_name or "-",
                "in_time": arr_rec.checkin_date.strftime("%I:%M %p") if arr_rec.checkin_date else "-",
                "out_date": arr_rec.checkout_date.strftime("%d/%m/%Y") if arr_rec.checkout_date else "-",
                "booking_no": arr_rec.name or "-",
                "plan": arr_rec.plan.upper() if arr_rec.plan else "BB",
            })
            a_idx += 1

        departures_records = self.env["room.booking"].search([
            ("checkout_date", ">=", dt_start),
            ("checkout_date", "<=", dt_end),
            ("state", "in", ["check_out", "done", "check_in"]),
        ], order="checkout_date asc")

        departures_list = []
        d_idx = 1
        for dep_rec in departures_records:
            rate = sum(dep_rec.room_line_ids.mapped("price_total"))
            departures_list.append({
                "s_no": d_idx,
                "guest_name": dep_rec.partner_id.name or "-",
                "room_no": dep_rec.room_name or "-",
                "out_time": dep_rec.checkout_date.strftime("%I:%M %p") if dep_rec.checkout_date else "-",
                "invoice_no": dep_rec.hotel_invoice_id.name if dep_rec.hotel_invoice_id else "-",
                "company": dep_rec.partner_id.parent_id.name if dep_rec.partner_id.parent_id else (dep_rec.partner_id.company_name or "-"),
                "rate": f"{rate:,.2f}",
                "booking_no": dep_rec.name or "-",
            })
            d_idx += 1

        # -------------------------------------------------------------
        # 4. DAILY ROOM RENT / ACCRUED CHARGES
        # -------------------------------------------------------------
        daily_rent_list = []
        r_idx = 1
        for b in active_bookings:
            for rline in b.room_line_ids:
                r_in = rline.checkin_date or b.checkin_date
                r_out = rline.checkout_date or b.checkout_date
                if r_in and r_in > dt_end:
                    continue
                if r_out and r_out < dt_start:
                    continue
                pax = rline.room_id.num_person if (rline.room_id and rline.room_id.num_person) else 1
                company_name = b.partner_id.parent_id.name if b.partner_id.parent_id else (b.partner_id.company_name or "ACCOUNT DIRECT")
                rent = rline.price_unit if rline.price_unit else (rline.price_subtotal / (b.duration or 1) if b.duration else rline.price_subtotal)
                checkin_str = (r_in or b.checkin_date).strftime("%d/%m/%Y") if (r_in or b.checkin_date) else "-"

                daily_rent_list.append({
                    "s_no": r_idx,
                    "name": b.partner_id.name or "-",
                    "room_no": rline.room_id.name if rline.room_id else (b.room_name or "-"),
                    "card_no": b.name or "-",
                    "check_in": checkin_str,
                    "pax": pax,
                    "company_name": company_name,
                    "rent": f"{rent:,.2f}",
                })
                r_idx += 1

        # -------------------------------------------------------------
        # 5. CASH REPORT / POS & DIRECT COLLECTIONS
        # -------------------------------------------------------------
        cash_records = []
        method_totals = {}
        total_debit = 0.0
        total_credit = 0.0

        if "pos.payment" in self.env:
            pos_payments = self.env["pos.payment"].search([
                ("payment_date", ">=", dt_start),
                ("payment_date", "<=", dt_end),
            ], order="payment_date asc")
            for pp in pos_payments:
                order = pp.pos_order_id
                dt = pp.payment_date or order.date_order
                m_name = pp.payment_method_id.name if pp.payment_method_id else "Cash"
                code = "CAS" if "cash" in m_name.lower() else m_name.upper()[:8]
                partner_name = order.partner_id.name if order.partner_id else (order.booking_id.partner_id.name if order.booking_id else "Walk-in Guest")
                amount = pp.amount
                credit = amount if amount >= 0 else 0.0
                debit = abs(amount) if amount < 0 else 0.0
                method_totals[m_name] = method_totals.get(m_name, 0.0) + credit

                cash_records.append({
                    "dt": dt,
                    "date": dt.strftime("%d/%m/%Y %I:%M %p") if dt else "-",
                    "cas": code,
                    "name": partner_name,
                    "voucher_no": order.pos_reference or order.name or "-",
                    "remarks": f"POS - {order.session_id.name if order.session_id else 'Restaurant'}",
                    "card_no": order.booking_id.name if order.booking_id else "-",
                    "room_no": order.booking_id.room_name or "-",
                    "debit": debit,
                    "credit": credit,
                })

        if "account.payment" in self.env:
            payments = self.env["account.payment"].search([
                ("date", ">=", audit_date),
                ("date", "<=", audit_date),
                ("state", "in", ["posted", "paid"]),
            ], order="date asc")
            for pay in payments:
                j_name = pay.journal_id.name if pay.journal_id else "Bank/Cash"
                code = "CAS" if "cash" in j_name.lower() else j_name.upper()[:8]
                dt = datetime.combine(pay.date, time.min) if pay.date else False
                booking = self.env["room.booking"].search([
                    "|", ("hotel_invoice_id.payment_ids", "in", [pay.id]),
                    ("partner_id", "=", pay.partner_id.id)
                ], limit=1)

                amt = pay.amount
                credit = amt if pay.payment_type == "inbound" else 0.0
                debit = amt if pay.payment_type == "outbound" else 0.0
                method_totals[j_name] = method_totals.get(j_name, 0.0) + credit

                cash_records.append({
                    "dt": dt or datetime.min,
                    "date": pay.date.strftime("%d/%m/%Y") if pay.date else "-",
                    "cas": code,
                    "name": pay.partner_id.name or "-",
                    "voucher_no": pay.name or "-",
                    "remarks": pay.ref or "Hotel Collection / Bill Settlement",
                    "card_no": booking.name if booking else "-",
                    "room_no": booking.room_name if booking else "-",
                    "debit": debit,
                    "credit": credit,
                })

        cash_records.sort(key=lambda x: x["dt"] or datetime.min)
        cash_lines = []
        running_bal = 0.0
        c_idx = 1
        for cr in cash_records:
            deb = cr["debit"]
            crd = cr["credit"]
            running_bal += (crd - deb)
            total_debit += deb
            total_credit += crd
            cash_lines.append({
                "s_no": c_idx,
                "date": cr["date"],
                "cas": cr["cas"],
                "name": cr["name"],
                "voucher_no": cr["voucher_no"],
                "remarks": cr["remarks"],
                "card_no": cr["card_no"],
                "room_no": cr["room_no"],
                "debit": f"{deb:,.2f}" if deb else "-",
                "credit": f"{crd:,.2f}" if crd else "-",
                "balance": f"{running_bal:,.2f}",
            })
            c_idx += 1

        method_summary = [{"method": k, "total": f"{v:,.2f}"} for k, v in sorted(method_totals.items())]

        return {
            "cover": {
                "audit_date_formatted": audit_date.strftime("%d %B %Y").upper(),
                "audit_date": audit_date.strftime("%d/%m/%Y"),
                "audited_by": self.user_id.name or "Auditor",
                "company_name": self.env.company.name,
                "notes": self.notes or "",
            },
            "kpis": {
                "total_rooms": total_rooms,
                "available_rooms": available_rooms_count,
                "occupied_rooms": occupied_count,
                "vacant_rooms": vacant_count,
                "maintenance_rooms": maintenance_count,
                "house_use_cleaning": cleaning_count,
                "occupancy_rate": f"{occupancy_rate:.1f}%",
                "arrivals": len(arrivals_list),
                "departures": len(departures_list),
                "inhouse_pax": inhouse_pax,
                "arr": f"{arr:,.2f}",
                "revpar": f"{revpar:,.2f}",
                "agr": f"{agr:,.2f}",
                "total_room_rent": f"{total_room_rent:,.2f}",
                "total_restaurant_pos": f"{total_restaurant_pos:,.2f}",
                "grand_total_revenue": f"{grand_total_revenue:,.2f}",
            },
            "inhouse_list": inhouse_list,
            "arrivals_list": arrivals_list,
            "departures_list": departures_list,
            "daily_rent_list": daily_rent_list,
            "cash_lines": cash_lines,
            "method_summary": method_summary,
            "total_debit": f"{total_debit:,.2f}",
            "total_credit": f"{total_credit:,.2f}",
            "closing_balance": f"{running_bal:,.2f}",
        }

    def get_xlsx_report(self, data, response):
        """Generate Multi-Tab XLSX Night Audit Workbook."""
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {"in_memory": True})
        
        head_format = workbook.add_format({"align": "center", "bold": True, "font_size": 14, "border": 1, "bg_color": "#2C3E50", "font_color": "#FFFFFF"})
        tbl_header = workbook.add_format({"bold": True, "align": "center", "bg_color": "#D3D3D3", "border": 1, "font_size": 10})
        tbl_cell = workbook.add_format({"align": "left", "border": 1, "font_size": 10})
        tbl_center = workbook.add_format({"align": "center", "border": 1, "font_size": 10})
        tbl_num = workbook.add_format({"align": "right", "border": 1, "font_size": 10})
        tbl_total = workbook.add_format({"bold": True, "align": "right", "border": 1, "font_size": 10, "bg_color": "#EAEAEA"})

        audit = data.get("audit_data", {})
        cov = audit.get("cover", {})
        kpis = audit.get("kpis", {})

        # Tab 1: KPI Summary
        s1 = workbook.add_worksheet("1. Summary & KPIs")
        s1.merge_range("A1:D1", f"NIGHT AUDIT PACK - {cov.get('audit_date_formatted', '-')}", head_format)
        s1.write("A3", "Audited By:", tbl_header)
        s1.write("B3", cov.get("audited_by", "-"), tbl_cell)
        s1.write("C3", "Audit Date:", tbl_header)
        s1.write("D3", cov.get("audit_date", "-"), tbl_cell)

        kpi_rows = [
            ("Total Rooms", kpis.get("total_rooms", 0)),
            ("Occupied Rooms", kpis.get("occupied_rooms", 0)),
            ("Available Rooms", kpis.get("available_rooms", 0)),
            ("Occupancy Rate", kpis.get("occupancy_rate", "0%")),
            ("ARR (Average Room Rate)", kpis.get("arr", "0.00")),
            ("RevPAR", kpis.get("revpar", "0.00")),
            ("Total Room Rent", kpis.get("total_room_rent", "0.00")),
            ("Restaurant & POS Revenue", kpis.get("total_restaurant_pos", "0.00")),
            ("Grand Total Revenue", kpis.get("grand_total_revenue", "0.00")),
        ]
        r = 5
        for label, val in kpi_rows:
            s1.write(r, 0, label, tbl_header)
            s1.write(r, 1, str(val), tbl_cell)
            r += 1

        # Tab 2: In-House Guests
        s2 = workbook.add_worksheet("2. In-House Guests")
        s2.merge_range("A1:H1", "IN-HOUSE GUESTS", head_format)
        headers2 = ["S No", "Guest Name", "Room No", "Check In", "Check Out", "Pricelist", "Nationality", "Room Rate"]
        for c, h in enumerate(headers2):
            s2.write(2, c, h, tbl_header)
        r2 = 3
        for item in audit.get("inhouse_list", []):
            s2.write(r2, 0, item["s_no"], tbl_center)
            s2.write(r2, 1, item["guest_name"], tbl_cell)
            s2.write(r2, 2, item["room_no"], tbl_center)
            s2.write(r2, 3, item["checkin"], tbl_center)
            s2.write(r2, 4, item["checkout"], tbl_center)
            s2.write(r2, 5, item["pricelist"], tbl_cell)
            s2.write(r2, 6, item["nationality"], tbl_center)
            s2.write(r2, 7, item["room_rate"], tbl_num)
            r2 += 1

        # Tab 3: Daily Room Rent
        s3 = workbook.add_worksheet("3. Daily Room Charges")
        s3.merge_range("A1:H1", "DAILY ACCRUED ROOM CHARGES", head_format)
        headers3 = ["S No", "Name", "Room No", "Card No", "Check In", "Pax", "Company Name", "Rent"]
        for c, h in enumerate(headers3):
            s3.write(2, c, h, tbl_header)
        r3 = 3
        for item in audit.get("daily_rent_list", []):
            s3.write(r3, 0, item["s_no"], tbl_center)
            s3.write(r3, 1, item["name"], tbl_cell)
            s3.write(r3, 2, item["room_no"], tbl_center)
            s3.write(r3, 3, item["card_no"], tbl_center)
            s3.write(r3, 4, item["check_in"], tbl_center)
            s3.write(r3, 5, item["pax"], tbl_center)
            s3.write(r3, 6, item["company_name"], tbl_cell)
            s3.write(r3, 7, item["rent"], tbl_num)
            r3 += 1

        # Tab 4: Cash & POS
        s4 = workbook.add_worksheet("4. Cash & POS Collections")
        s4.merge_range("A1:K1", "CASH & POS COLLECTIONS", head_format)
        headers4 = ["S.No", "Date", "CAS", "Name", "Voucher No", "Remarks", "CardNo", "RoomNo", "Debit", "Credit", "Balance"]
        for c, h in enumerate(headers4):
            s4.write(2, c, h, tbl_header)
        r4 = 3
        for item in audit.get("cash_lines", []):
            s4.write(r4, 0, item["s_no"], tbl_center)
            s4.write(r4, 1, item["date"], tbl_center)
            s4.write(r4, 2, item["cas"], tbl_center)
            s4.write(r4, 3, item["name"], tbl_cell)
            s4.write(r4, 4, item["voucher_no"], tbl_center)
            s4.write(r4, 5, item["remarks"], tbl_cell)
            s4.write(r4, 6, item["card_no"], tbl_center)
            s4.write(r4, 7, item["room_no"], tbl_center)
            s4.write(r4, 8, item["debit"], tbl_num)
            s4.write(r4, 9, item["credit"], tbl_num)
            s4.write(r4, 10, item["balance"], tbl_num)
            r4 += 1

        workbook.close()
        output.seek(0)
        response.stream.write(output.read())
        output.close()
