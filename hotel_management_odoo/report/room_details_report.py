# -*- coding: utf-8 -*-
from odoo import api, models


class ReportRoomDetails(models.AbstractModel):
    """Abstract model for generating the Room Details QWeb PDF Report."""

    _name = 'report.hotel_management_odoo.report_room_details'
    _description = 'Room Details Report Parser'

    @api.model
    def _get_report_values(self, docids, data=None):
        """Fetch all hotel rooms when printed from Reporting menu or selection."""
        if docids:
            docs = self.env['hotel.room'].browse(docids)
        else:
            docs = self.env['hotel.room'].search([])

        if not docs:
            docs = self.env['hotel.room'].search([])

        return {
            'doc_ids': docs.ids,
            'doc_model': 'hotel.room',
            'docs': docs,
        }
