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


class RoomAnalysisWizard(models.TransientModel):
    """Wizard for generating Room Analysis Summary Report (24-hr Occupancy & KPIs)."""

    _name = "room.analysis.wizard"
    _description = "Room Analysis Summary Report Wizard"

    date = fields.Date(string="Analysis Date", default=fields.Date.context_today, required=True, help="Select the 24-hour analysis date")

    def action_print_pdf(self):
        """Generate PDF Room Analysis Summary Report."""
        data = {
            "analysis_data": self.generate_data(),
        }
        return self.env.ref("hotel_management_odoo.action_report_room_analysis").report_action(self, data=data)

    def action_print_excel(self):
        """Generate Excel Room Analysis Summary Report."""
        data = {
            "analysis_data": self.generate_data(),
        }
        return {
            "type": "ir.actions.report",
            "data": {
                "model": "room.analysis.wizard",
                "options": json.dumps(data, default=json_default),
                "output_format": "xlsx",
                "report_name": "Room Analysis Summary",
            },
            "report_type": "xlsx",
        }

    def generate_data(self):
        """Compute all 24-hr hotel occupancy & financial performance KPIs for the target date."""
        self.ensure_one()
        target_date = self.date
        dt_start = datetime.combine(target_date, time.min)
        dt_end = datetime.combine(target_date, time.max)

        # 1. Rooms inventory
        all_rooms = self.env["hotel.room"].search([])
        total_rooms = len(all_rooms)
        
        # Check rooms under active maintenance requests
        maint_requests = self.env["maintenance.request"].search([
            ("type", "=", "room"),
            ("state", "in", ["draft", "assign", "ongoing", "support"])
        ])
        maintenance_room_ids = maint_requests.mapped("room_maintenance_ids.id")
        maintenance_count = len(set(maintenance_room_ids))

        # Check rooms under active cleaning requests
        cleaning_requests = self.env["cleaning.request"].search([
            ("cleaning_type", "=", "room"),
            ("state", "in", ["draft", "assign", "ongoing", "support"])
        ])
        cleaning_room_ids = cleaning_requests.mapped("room_id.id")
        cleaning_count = len(set(cleaning_room_ids))
        
        available_rooms_count = max(0, total_rooms - maintenance_count)

        # 2. Active bookings covering the 24-hr window
        active_bookings = self.env["room.booking"].search([
            ("checkin_date", "<=", dt_end),
            ("checkout_date", ">=", dt_start),
            ("state", "in", ["check_in", "reserved", "check_out", "done"]),
        ])

        # Occupied rooms set & details
        occupied_room_ids = set()
        inhouse_pax = 0
        total_room_rent = 0.0
        room_breakdown = []

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

                room_breakdown.append({
                    "room_no": rline.room_id.name if rline.room_id else (b.room_name or "-"),
                    "room_type": dict(rline.room_id._fields['room_type'].selection).get(rline.room_id.room_type, '-') if (rline.room_id and rline.room_id.room_type) else "-",
                    "floor": rline.room_id.floor_id.name if (rline.room_id and rline.room_id.floor_id) else "-",
                    "guest_name": b.partner_id.name or "-",
                    "booking_no": b.name or "-",
                    "pax": pax,
                    "rent": f"{rent:,.2f}",
                })

        occupied_count = len(occupied_room_ids)
        vacant_count = max(0, available_rooms_count - occupied_count)
        occupancy_rate = (occupied_count / available_rooms_count * 100.0) if available_rooms_count > 0 else 0.0

        # 3. Arrivals & Departures on Date
        arrivals = self.env["room.booking"].search([
            ("checkin_date", ">=", dt_start),
            ("checkin_date", "<=", dt_end),
            ("state", "in", ["check_in", "reserved", "check_out", "done"]),
        ])
        departures = self.env["room.booking"].search([
            ("checkout_date", ">=", dt_start),
            ("checkout_date", "<=", dt_end),
            ("state", "in", ["check_in", "reserved", "check_out", "done"]),
        ])
        arrivals_count = len(arrivals)
        departures_count = len(departures)

        # 4. Financial KPIs
        arr = (total_room_rent / occupied_count) if occupied_count > 0 else 0.0
        revpar = (total_room_rent / available_rooms_count) if available_rooms_count > 0 else 0.0
        agr = (total_room_rent / inhouse_pax) if inhouse_pax > 0 else 0.0

        # 5. Restaurant, POS, & Extra Services on date
        # Search POS orders on that date
        total_restaurant_pos = 0.0
        if "pos.order" in self.env:
            pos_orders = self.env["pos.order"].search([
                ("date_order", ">=", dt_start),
                ("date_order", "<=", dt_end),
                ("state", "in", ["paid", "done", "invoiced"]),
            ])
            total_restaurant_pos += sum(pos_orders.mapped("amount_total"))

        # Add food booking lines on that date
        food_lines = self.env["food.booking.line"].search([
            ("booking_id.checkin_date", "<=", dt_end),
            ("booking_id.checkout_date", ">=", dt_start),
        ])
        total_restaurant_pos += sum(food_lines.mapped("price_total"))

        grand_total_revenue = total_room_rent + total_restaurant_pos

        return {
            "date": target_date.strftime("%d/%m/%Y"),
            "kpis": {
                "total_rooms": total_rooms,
                "available_rooms": available_rooms_count,
                "occupied_rooms": occupied_count,
                "vacant_rooms": vacant_count,
                "maintenance_rooms": maintenance_count,
                "house_use_cleaning": cleaning_count,
                "occupancy_rate": f"{occupancy_rate:.1f}%",
                "arrivals": arrivals_count,
                "departures": departures_count,
                "inhouse_pax": inhouse_pax,
                "arr": f"{arr:,.2f}",
                "revpar": f"{revpar:,.2f}",
                "agr": f"{agr:,.2f}",
                "total_room_rent": f"{total_room_rent:,.2f}",
                "total_restaurant_pos": f"{total_restaurant_pos:,.2f}",
                "grand_total_revenue": f"{grand_total_revenue:,.2f}",
            },
            "room_breakdown": room_breakdown,
        }

    def get_xlsx_report(self, data, response):
        """Generate XLSX Room Analysis Summary Report."""
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {"in_memory": True})
        sheet = workbook.add_worksheet("Room Analysis")

        head_format = workbook.add_format({"align": "center", "bold": True, "font_size": 16, "border": 1})
        sub_format = workbook.add_format({"align": "center", "italic": True, "font_size": 10})
        sec_header = workbook.add_format({"bold": True, "font_size": 12, "bg_color": "#2C3E50", "font_color": "#FFFFFF", "border": 1})
        kpi_label = workbook.add_format({"bold": True, "font_size": 10, "border": 1, "bg_color": "#F8F9FA"})
        kpi_val = workbook.add_format({"align": "right", "font_size": 10, "border": 1})
        kpi_val_bold = workbook.add_format({"align": "right", "bold": True, "font_size": 11, "border": 1, "bg_color": "#EAEAEA"})

        tbl_header = workbook.add_format({"bold": True, "align": "center", "bg_color": "#D3D3D3", "border": 1, "font_size": 10})
        tbl_cell = workbook.add_format({"align": "left", "border": 1, "font_size": 10})
        tbl_center = workbook.add_format({"align": "center", "border": 1, "font_size": 10})
        tbl_num = workbook.add_format({"align": "right", "border": 1, "font_size": 10})

        anl = data.get("analysis_data", {})
        kpis = anl.get("kpis", {})

        sheet.merge_range("A1:G1", "ROOM ANALYSIS SUMMARY REPORT", head_format)
        sheet.merge_range("A2:G2", f"24-Hour Performance Date: {anl.get('date', '-')}", sub_format)

        sheet.set_column("A:A", 28)
        sheet.set_column("B:B", 18)
        sheet.set_column("C:C", 4)
        sheet.set_column("D:D", 28)
        sheet.set_column("E:E", 18)
        sheet.set_column("F:F", 16)
        sheet.set_column("G:G", 16)

        # Section 1: Room Occupancy & Inventory
        sheet.merge_range("A4:B4", "ROOM OCCUPANCY & INVENTORY", sec_header)
        sheet.merge_range("D4:E4", "FINANCIAL PERFORMANCE (24-HR)", sec_header)

        # Row 1
        sheet.write("A5", "Total Hotel Rooms", kpi_label)
        sheet.write("B5", kpis.get("total_rooms", 0), kpi_val)
        sheet.write("D5", "Total Room Rent", kpi_label)
        sheet.write("E5", kpis.get("total_room_rent", "0.00"), kpi_val_bold)

        # Row 2
        sheet.write("A6", "Available Rooms", kpi_label)
        sheet.write("B6", kpis.get("available_rooms", 0), kpi_val)
        sheet.write("D6", "Restaurant & POS Revenue", kpi_label)
        sheet.write("E6", kpis.get("total_restaurant_pos", "0.00"), kpi_val)

        # Row 3
        sheet.write("A7", "Occupied Rooms", kpi_label)
        sheet.write("B7", kpis.get("occupied_rooms", 0), kpi_val_bold)
        sheet.write("D7", "Grand Total Daily Revenue", kpi_label)
        sheet.write("E7", kpis.get("grand_total_revenue", "0.00"), kpi_val_bold)

        # Row 4
        sheet.write("A8", "Vacant Rooms", kpi_label)
        sheet.write("B8", kpis.get("vacant_rooms", 0), kpi_val)
        sheet.write("D8", "ARR (Average Room Rate)", kpi_label)
        sheet.write("E8", kpis.get("arr", "0.00"), kpi_val)

        # Row 5
        sheet.write("A9", "Maintenance / Under Repair", kpi_label)
        sheet.write("B9", kpis.get("maintenance_rooms", 0), kpi_val)
        sheet.write("D9", "RevPAR (Rev per Avail Room)", kpi_label)
        sheet.write("E9", kpis.get("revpar", "0.00"), kpi_val)

        # Row 6
        sheet.write("A10", "House Use / Cleaning", kpi_label)
        sheet.write("B10", kpis.get("house_use_cleaning", 0), kpi_val)
        sheet.write("D10", "Average Guest Rate (AGR)", kpi_label)
        sheet.write("E10", kpis.get("agr", "0.00"), kpi_val)

        # Row 7
        sheet.write("A11", "Occupancy Rate (%)", kpi_label)
        sheet.write("B11", kpis.get("occupancy_rate", "0.0%"), kpi_val_bold)
        sheet.write("D11", "In-House Guests (Pax)", kpi_label)
        sheet.write("E11", kpis.get("inhouse_pax", 0), kpi_val)

        # Row 8
        sheet.write("A12", "Arrivals (Check-Ins Today)", kpi_label)
        sheet.write("B12", kpis.get("arrivals", 0), kpi_val)
        sheet.write("D12", "Departures (Check-Outs Today)", kpi_label)
        sheet.write("E12", kpis.get("departures", 0), kpi_val)

        # Breakdown table
        row = 15
        sheet.merge_range(f"A{row}:G{row}", "OCCUPIED ROOM BREAKDOWN DETAILS", sec_header)
        row += 1
        headers = ["Room No", "Room Type", "Floor", "Guest Name", "Folio No", "Pax", "Daily Rent"]
        for col_idx, htext in enumerate(headers):
            sheet.write(row, col_idx, htext, tbl_header)

        row += 1
        for item in anl.get("room_breakdown", []):
            sheet.write(row, 0, item["room_no"], tbl_center)
            sheet.write(row, 1, item["room_type"], tbl_cell)
            sheet.write(row, 2, item["floor"], tbl_center)
            sheet.write(row, 3, item["guest_name"], tbl_cell)
            sheet.write(row, 4, item["booking_no"], tbl_center)
            sheet.write(row, 5, item["pax"], tbl_center)
            sheet.write(row, 6, item["rent"], tbl_num)
            row += 1

        workbook.close()
        output.seek(0)
        response.stream.write(output.read())
        output.close()
