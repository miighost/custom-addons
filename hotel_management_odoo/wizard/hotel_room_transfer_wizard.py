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
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class HotelRoomTransferWizard(models.TransientModel):
    """Wizard to quickly and simply transfer an in-house or reserved guest to a new room."""

    _name = "hotel.room.transfer.wizard"
    _description = "Room Transfer Wizard"

    booking_id = fields.Many2one("room.booking", string="Booking / Folio", required=True, readonly=True)
    current_room_line_id = fields.Many2one(
        "room.booking.line",
        string="Current Room Line",
        required=True,
        domain="[('booking_id', '=', booking_id)]",
        help="Select the current room line to transfer from"
    )
    current_room_id = fields.Many2one(
        "hotel.room",
        string="Current Room",
        related="current_room_line_id.room_id",
        readonly=True
    )
    new_room_id = fields.Many2one(
        "hotel.room",
        string="New Room",
        required=True,
        domain="[('status', '=', 'available'), ('is_room_avail', '=', True)]",
        help="Select an available room to transfer the guest into"
    )
    send_to_cleaning = fields.Boolean(
        string="Send to Cleaning (Housekeeping)",
        default=True,
        help="Create a housekeeping cleaning request task for the previous room"
    )
    reason = fields.Char(string="Reason for Transfer", placeholder="e.g. AC repair, Room upgrade, Guest preference")

    def action_confirm_transfer(self):
        """Execute the room transfer, update room statuses, create cleaning task if requested, and update folio."""
        self.ensure_one()
        booking = self.booking_id
        old_room = self.current_room_id
        new_room = self.new_room_id
        line = self.current_room_line_id

        if not old_room or not new_room:
            raise ValidationError("Please select both current room and new room.")
        if old_room.id == new_room.id:
            raise ValidationError("New room must be different from the current room.")

        # 1. Update Old Room status to Available
        old_room.write({
            "status": "available",
            "is_room_avail": True,
        })

        # 2. If Send to Cleaning is checked, create Housekeeping Cleaning Request
        if self.send_to_cleaning:
            team = self.env["cleaning.team"].search([], limit=1)
            if team:
                self.env["cleaning.request"].create({
                    "cleaning_type": "room",
                    "room_id": old_room.id,
                    "team_id": team.id,
                    "description": f"Housekeeping cleaning for Room {old_room.name} following transfer of booking {booking.name} to Room {new_room.name} (Reason: {self.reason or 'Room Transfer'}).",
                    "state": "draft",
                })

        # 3. Update New Room status to Occupied (if booking is active in check_in)
        if booking.state == "check_in":
            new_room.write({
                "status": "occupied",
                "is_room_avail": False,
            })
        elif booking.state == "reserved":
            new_room.write({
                "status": "reserved",
                "is_room_avail": False,
            })

        # 4. Update the room booking line to point to the new room
        line.write({
            "room_id": new_room.id,
        })
        line._compute_price_subtotal()

        # 5. Refresh booking computed fields
        booking._compute_room_name()
        booking._compute_amount_untaxed()

        # 6. Log transfer in booking chatter
        cleaning_text = "Yes (Housekeeping task generated)" if self.send_to_cleaning else "No"
        log_msg = (
            f"<b>Room Transfer Executed:</b><br/>"
            f"• <b>From Room:</b> {old_room.name}<br/>"
            f"• <b>To Room:</b> {new_room.name}<br/>"
            f"• <b>Send to Cleaning:</b> {cleaning_text}<br/>"
            f"• <b>Reason:</b> {self.reason or 'Not specified'}"
        )
        booking.message_post(body=log_msg)

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Room Transferred Successfully",
                "message": f"Guest moved from Room {old_room.name} to Room {new_room.name}.",
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.act_window_close"},
            },
        }
