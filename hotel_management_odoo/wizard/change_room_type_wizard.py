# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ChangeRoomTypeWizard(models.TransientModel):
    """Wizard for mass updating Room Type of multiple selected rooms."""

    _name = "change.room.type.wizard"
    _description = "Mass Change Room Type Wizard"

    room_type = fields.Selection([
        ('deluxe_suite', 'DELUXE SUITE'),
        ('deluxe_single', 'DELUXE SINGLE'),
        ('standard_room', 'STANDARD ROOM')
    ], string="New Room Type", required=True, default="deluxe_single")

    def action_apply_room_type(self):
        """Apply selected room type to all active selected rooms."""
        self.ensure_one()
        active_ids = self.env.context.get('active_ids', [])
        rooms = self.env['hotel.room'].browse(active_ids)
        if rooms:
            rooms.write({'room_type': self.room_type})
            for room in rooms:
                room._onchange_room_type()
        return {'type': 'ir.actions.act_window_close'}
