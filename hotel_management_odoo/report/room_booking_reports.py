# -*- coding: utf-8 -*-
from odoo import api, models


class ReportRoomBookingOrder(models.AbstractModel):
    """Abstract model for generating the Room Booking Order QWeb PDF Report."""

    _name = 'report.hotel_management_odoo.report_room_booking'
    _description = 'Room Booking Order Report Parser'

    @api.model
    def _get_report_values(self, docids, data=None):
        """Handle printing both from Wizard (with data) and directly from Form View (docids)."""
        if data and data.get('booking'):
            booking_lines = data['booking']
        else:
            docs = self.env['room.booking'].browse(docids) if docids else self.env['room.booking'].search([])
            booking_lines = []
            for rec in docs:
                rooms = rec.room_line_ids.mapped('room_id.name')
                partner_name = rec.partner_id.name if rec.partner_id else '-'
                if rooms:
                    for room in rooms:
                        booking_lines.append({
                            'partner_id': partner_name,
                            'room': room,
                            'checkin_date': rec.checkin_date,
                            'checkout_date': rec.checkout_date,
                            'name': rec.name,
                        })
                else:
                    booking_lines.append({
                        'partner_id': partner_name,
                        'room': rec.room_name or '-',
                        'checkin_date': rec.checkin_date,
                        'checkout_date': rec.checkout_date,
                        'name': rec.name,
                    })

        return {
            'doc_ids': docids,
            'doc_model': 'room.booking',
            'booking': booking_lines,
        }
