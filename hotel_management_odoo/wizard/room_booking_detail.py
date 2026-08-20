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


class RoomBookingWizard(models.TransientModel):
    """Pdf Report for room Booking"""

    _name = "room.booking.detail"
    _description = "Room Booking Details"

    checkin = fields.Date(help="Choose the Checkin Date", string="Checkin")
    checkout = fields.Date(help="Choose the Checkout Date", string="Checkout")
    room_id = fields.Many2one("product.template", string="Room",
                              help="Choose The Room")

    def action_room_booking_pdf(self):
        """Button action_room_booking_pdf function"""
        data = {
            "booking": self.generate_data(),
        }
        return self.env.ref(
            "hotel_management_odoo.action_report_room_booking"
        ).report_action(self, data=data)

    def action_room_booking_excel(self):
        """Button action for creating Room Booking Excel report"""
        data = {
            "booking": self.generate_data(),
        }
        return {
            "type": "ir.actions.report",
            "data": {
                "model": "room.booking.detail",
                "options": json.dumps(data, default=json_default),
                "output_format": "xlsx",
                "report_name": "Excel Report",
            },
            "report_type": "xlsx",
        }

    def generate_data(self):
        """Generate data to be printed in the report"""
        domain = []
        room_list = []
        if self.checkin and self.checkout:
            if self.checkin > self.checkout:
                raise ValidationError(
                    _("Check-in date should be less than Check-out date")
                )
        if self.checkin:
            domain.append(
                ("checkin_date", ">=", self.checkin),
            )
        if self.checkout:
            domain.append(
                ("checkout_date", "<", self.checkout + timedelta(days=1)),
            )
        if self.room_id:
            domain.append(
                ("room_id", "=", self.room_id.id),
            )

        state_labels = {
            'draft': 'Draft',
            'reserved': 'Reserved',
            'check_in': 'Check In',
            'check_out': 'Check Out',
            'cancel': 'Cancelled',
            'done': 'Done',
        }
        room_booking_lines = self.env["room.booking.line"].search(domain)
        for line in room_booking_lines:
            room_name = line.room_id.name if line.room_id and line.room_id.exists() else ""
            partner_name = line.booking_id.partner_id.name if line.booking_id and line.booking_id.partner_id else ""
            booking_name = line.booking_id.name if line.booking_id else ""
            raw_state = line.booking_id.state if line.booking_id else ""
            room_list.append({
                "partner_id": partner_name,
                "name": booking_name,
                "checkin_date": line.checkin_date,
                "checkout_date": line.checkout_date,
                "room": room_name,
                "state": state_labels.get(raw_state, raw_state),
            })
        return room_list

    def _format_datetime(self, value):
        """Safely format a datetime value that may be a str or datetime object."""
        if not value:
            return ""
        if isinstance(value, str):
            # search_read / JSON round-trip returns ISO strings like
            # '2026-06-01 10:00:00' — parse then reformat for consistency
            try:
                value = datetime.strptime(value[:19], '%Y-%m-%d %H:%M:%S')
            except ValueError:
                return value  # return as-is if unparseable
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
        sheet.merge_range("A1:G1", "Room Booking", head)
        sheet.set_column("A2:G2", 18)
        sheet.set_row(0, 30)
        sheet.set_row(1, 20)
        sheet.write("A2", "Sl No.", cell_format)
        sheet.write("B2", "Guest Name", cell_format)
        sheet.write("C2", "Room No.", cell_format)
        sheet.write("D2", "Check In", cell_format)
        sheet.write("E2", "Check Out", cell_format)
        sheet.write("F2", "Reference No.", cell_format)
        sheet.write("G2", "Status", cell_format)
        row = 2
        column = 0
        value = 1
        for i in data["booking"]:
            sheet.write(row, column, value, body)
            sheet.write(row, column + 1, i["partner_id"], body)
            sheet.write(row, column + 2, i["room"], body)
            sheet.write(row, column + 3, self._format_datetime(i["checkin_date"]), body)
            sheet.write(row, column + 4, self._format_datetime(i["checkout_date"]), body)
            sheet.write(row, column + 5, i["name"], body)
            sheet.write(row, column + 6, i["state"], body)
            row = row + 1
            value = value + 1
        workbook.close()
        output.seek(0)
        response.stream.write(output.read())
        output.close()