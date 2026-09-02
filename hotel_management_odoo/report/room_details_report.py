# -*- coding: utf-8 -*-
from odoo import api, models


class ReportRoomDetails(models.AbstractModel):
    """Abstract model for generating the Room Details QWeb PDF Report."""

    _name = 'report.hotel_management_odoo.report_room_details'
    _description = 'Room Details Report Parser'

    @api.model
    def _get_report_values(self, docids, data=None):
        """Fetch and group hotel rooms by Room Type / Category."""
        if docids:
            rooms = self.env['hotel.room'].browse(docids)
        else:
            rooms = self.env['hotel.room'].search([], order='room_type asc, name asc')

        if not rooms:
            rooms = self.env['hotel.room'].search([], order='room_type asc, name asc')

        # Get room_type selection dict for human-readable labels
        room_type_dict = dict(self.env['hotel.room']._fields['room_type'].selection)

        # Group rooms by room_type
        grouped_rooms = {}
        for room in rooms:
            type_label = room_type_dict.get(room.room_type, (room.room_type or 'STANDARD ROOM').upper())
            if type_label not in grouped_rooms:
                grouped_rooms[type_label] = []
            grouped_rooms[type_label].append(room)

        total_rooms_count = len(rooms)
        available_count = len(rooms.filtered(lambda r: r.status == 'available'))
        occupied_count = len(rooms.filtered(lambda r: r.status == 'occupied'))
        reserved_count = len(rooms.filtered(lambda r: r.status == 'reserved'))

        return {
            'doc_ids': rooms.ids,
            'doc_model': 'hotel.room',
            'docs': rooms,
            'grouped_rooms': grouped_rooms,
            'total_rooms_count': total_rooms_count,
            'available_count': available_count,
            'occupied_count': occupied_count,
            'reserved_count': reserved_count,
            'currency': self.env.company.currency_id,
        }
