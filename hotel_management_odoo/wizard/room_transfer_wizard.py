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
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class RoomTransferWizard(models.TransientModel):
    """Wizard to transfer a guest from one room to another during their stay."""
    _name = 'room.transfer.wizard'
    _description = 'Room Transfer Wizard'

    booking_id = fields.Many2one('room.booking', string='Booking', required=True, readonly=True)
    partner_id = fields.Many2one('res.partner', related='booking_id.partner_id', string='Guest', readonly=True)
    current_room_id = fields.Many2one('product.template', string='Current Room', required=True, readonly=True)
    new_room_id = fields.Many2one(
        'product.template',
        string='New Room',
        domain=[('is_room', '=', True), ('status', '=', 'available')],
        required=True,
        help="Select an available room to transfer the guest to."
    )
    send_to_cleaning = fields.Boolean(
        string='Mark Old Room for Cleaning',
        default=True,
        help="If checked, the vacated room will be set to 'cleaning' status for housekeeping."
    )
    reason = fields.Char(
        string='Transfer Reason',
        placeholder="e.g. Upgrade, Maintenance/AC issue, Guest request",
        help="Reason for transferring the room."
    )

    def action_transfer_room(self):
        """Perform room transfer, update room statuses, line details, and log the event."""
        self.ensure_one()

        if not self.new_room_id or not self.new_room_id.is_room:
            raise ValidationError(_("Please select a valid new room."))

        if self.new_room_id.id == self.current_room_id.id:
            raise ValidationError(_("The new room cannot be the same as the current room."))

        if self.new_room_id.status != 'available':
            raise ValidationError(_("Room '%s' is no longer available. Please select another room.") % self.new_room_id.name)

        booking = self.booking_id
        old_room = self.current_room_id
        new_room = self.new_room_id

        # 1. Find the booking line corresponding to the current room
        room_line = booking.room_line_ids.filtered(lambda l: l.room_id.id == old_room.id)
        if not room_line:
            # Fallback to first line if single room booking
            room_line = booking.room_line_ids[:1]

        if not room_line:
            raise ValidationError(_("No room line found on booking '%s' to transfer.") % booking.name)

        # 2. Update Old Room status
        old_room.sudo().write({
            'status': 'available',
            'is_room_avail': True if not self.send_to_cleaning else False,
        })

        # If cleaning team module is present and cleaning requested, create cleaning request
        if self.send_to_cleaning and 'cleaning.request' in self.env:
            try:
                self.env['cleaning.request'].sudo().create({
                    'name': _('Cleaning - %s (Room Transfer)') % old_room.name,
                    'room_id': old_room.id,
                    'state': 'draft',
                    'description': _('Room vacated following transfer to %s.') % new_room.name,
                })
            except Exception:
                pass

        # 3. Update New Room status to Occupied
        new_room.sudo().write({
            'status': 'occupied',
            'is_room_avail': False,
        })

        # 4. Update the room booking line
        room_line.write({
            'room_id': new_room.id,
        })
        # Trigger price and tax recomputations if needed
        room_line._compute_price_unit()
        room_line._compute_price_subtotal()

        # 5. Recompute booking room number
        booking._compute_room_number()

        # 6. Post audit log in booking chatter
        reason_str = (" (Reason: %s)" % self.reason) if self.reason else ""
        log_body = _("🔄 <b>Room Transfer Completed</b>: Guest transferred from <b>%s</b> to <b>%s</b>%s.") % (
            old_room.name, new_room.name, reason_str
        )
        if hasattr(booking, 'message_post'):
            booking.message_post(body=log_body)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'message': _("Room successfully transferred to %s!") % new_room.name,
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }
