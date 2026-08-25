# -*- coding: utf-8 -*-
from odoo import api, models


class ReportRoomStatus(models.AbstractModel):
    """Abstract model for generating the Room Status QWeb PDF Report."""

    _name = 'report.hotel_management_odoo.report_room_status'
    _description = 'Room Status Report Parser'

    @api.model
    def _get_report_values(self, docids, data=None):
        """Fetch all active room bookings when printed from Reporting menu or selection."""
        if docids:
            docs = self.env['room.booking'].browse(docids)
        else:
            docs = self.env['room.booking'].search([('state', 'in', ['reserved', 'check_in'])])

        if not docs:
            docs = self.env['room.booking'].search([('state', 'in', ['reserved', 'check_in'])])

        return {
            'doc_ids': docs.ids,
            'doc_model': 'room.booking',
            'docs': docs,
        }
