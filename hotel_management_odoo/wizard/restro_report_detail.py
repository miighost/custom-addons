# -*- coding: utf-8 -*-
#############################################################################
#
#    MiiG Solution
#
#    Copyright (C) 2026-TODAY MiiG Solution(<https://www.miigsolution.so>)
#    Author: MiiG Solution(<https://www.miigsolution.so>)
#
#    You can modify it under the terms of the GNU LESSER
#    GENERAL PUBLIC LICENSE (LGPL v3), Version 3.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU LESSER GENERAL PUBLIC LICENSE (LGPL v3) for more details.
#
#    You should have received a copy of the GNU LESSER GENERAL PUBLIC LICENSE
#    (LGPL v3) along with this program.
#    If not, see <http://www.gnu.org/licenses/>.
#
#############################################################################
import io
import json
from datetime import datetime, timedelta
from odoo import _, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import json_default

try:
    from odoo.tools.misc import xlsxwriter
except ImportError:
    import xlsxwriter


class RestroReportWizard(models.TransientModel):
    """Pdf and Excel Report for In-House Guest Restaurant / Restro Orders"""

    _name = "restro.report.detail"
    _description = "In-House Restro Report Details"

    checkin = fields.Date(help="Choose the Checkin Date", string="Checkin")
    checkout = fields.Date(help="Choose the Checkout Date", string="Checkout")
    room_id = fields.Many2one("product.template", string="Room",
                              help="Choose The Room")

    def action_restro_report_pdf(self):
        """Button action for creating Restro Report PDF"""
        data = {
            "booking": self.generate_data(),
        }
        return self.env.ref(
            "hotel_management_odoo.action_report_restro_report"
        ).report_action(self, data=data)

    def action_restro_report_excel(self):
        """Button action for creating Restro Report Excel"""
        data = {
            "booking": self.generate_data(),
        }
        return {
            "type": "ir.actions.report",
            "data": {
                "model": "restro.report.detail",
                "options": json.dumps(data, default=json_default),
                "output_format": "xlsx",
                "report_name": "Excel Report",
            },
            "report_type": "xlsx",
        }

    def generate_data(self):
        """Generate in-house room booking data for Restro Report"""
        domain = [("state", "=", "check_in")]
        if self.checkin and self.checkout:
            if self.checkin > self.checkout:
                raise ValidationError(
                    _("Check-in date should be less than Check-out date")
                )
        if self.checkin:
            domain.append(("checkin_date", ">=", self.checkin))
        if self.checkout:
            domain.append(("checkout_date", "<", self.checkout + timedelta(days=1)))
        if self.room_id:
            domain.append(("room_line_ids.room_id", "=", self.room_id.id))

        board_labels = {
            'ro': 'Room Only (RO)',
            'bb': 'Bed & Breakfast (BB)',
            'hb': 'Half Board (HB)',
            'fb': 'Full Board (FB)',
        }
        state_labels = {
            'draft': 'Draft',
            'reserved': 'Reserved',
            'check_in': 'Check In',
            'check_out': 'Check Out',
            'cancel': 'Cancelled',
            'done': 'Done',
        }
        restro_list = []
        inhouse_bookings = self.env["room.booking"].search(domain)
        for booking in inhouse_bookings:
            valid_rooms = booking.room_line_ids.filtered(lambda l: l.room_id and l.room_id.exists())
            room_names = ", ".join(valid_rooms.mapped("room_id.name")) if valid_rooms else ""
            partner = booking.partner_id
            guest_name = partner.name if partner else ""
            
            # Retrieve company name from guest partner
            company_name = "None"
            if partner:
                comp = partner.parent_id.name or partner.company_name
                if not comp and partner.commercial_company_name and partner.commercial_company_name != partner.name:
                    comp = partner.commercial_company_name
                if comp:
                    company_name = comp

            raw_board = booking.board_type if hasattr(booking, 'board_type') else 'ro'
            board_type_val = board_labels.get(raw_board, raw_board or "Room Only (RO)")
            restro_list.append({
                "guest_name": guest_name,
                "company_name": company_name,
                "room": room_names or booking.name,
                "board_type": board_type_val,
                "state": state_labels.get(booking.state, booking.state or "Check In"),
            })
        return restro_list

    def _format_datetime(self, value):
        """Safely format a datetime value that may be a str or datetime object."""
        if not value:
            return ""
        if isinstance(value, str):
            try:
                value = datetime.strptime(value[:19], '%Y-%m-%d %H:%M:%S')
            except ValueError:
                return value
        return value.strftime('%Y-%m-%d %H:%M:%S')

    def get_xlsx_report(self, data, response):
        """Organizing xlsx report"""
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {"in_memory": True})
        sheet = workbook.add_worksheet()
        cell_format = workbook.add_format(
            {"font_size": "14px", "bold": True, "align": "center",
             "border": True}
        )
        head = workbook.add_format(
            {"align": "center", "bold": True, "font_size": "23px",
             "border": True}
        )
        body = workbook.add_format(
            {"align": "left", "text_wrap": True, "border": True})
        sheet.merge_range("A1:F1", "In-House Guest Report", head)
        sheet.set_column("A2:F2", 22)
        sheet.set_row(0, 30)
        sheet.set_row(1, 20)
        sheet.write("A2", "SN", cell_format)
        sheet.write("B2", "Guest Name", cell_format)
        sheet.write("C2", "Company", cell_format)
        sheet.write("D2", "Room No", cell_format)
        sheet.write("E2", "Board Type", cell_format)
        sheet.write("F2", "Status", cell_format)
        row = 2
        column = 0
        value = 1
        for i in data["booking"]:
            sheet.write(row, column, value, body)
            sheet.write(row, column + 1, i["guest_name"], body)
            sheet.write(row, column + 2, i["company_name"], body)
            sheet.write(row, column + 3, i["room"], body)
            sheet.write(row, column + 4, i["board_type"], body)
            sheet.write(row, column + 5, i["state"], body)
            row = row + 1
            value = value + 1
        workbook.close()
        output.seek(0)
        response.stream.write(output.read())
        output.close()
