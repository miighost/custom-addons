# -*- coding: utf-8 -*-
from odoo import api, models


class ReportInHouseGuest(models.AbstractModel):
    """Abstract model for generating the In-House Guest List QWeb PDF Report."""

    _name = 'report.hotel_management_odoo.report_in_house_guest'
    _description = 'In-House Guest List Report Parser'

    @api.model
    def _get_report_values(self, docids, data=None):
        """Fetch all currently checked-in room bookings when printed from Reporting menu or selection."""
        if docids:
            docs = self.env['room.booking'].browse(docids)
        else:
            docs = self.env['room.booking'].search([('state', '=', 'check_in')])

        if not docs:
            docs = self.env['room.booking'].search([('state', '=', 'check_in')])

        return {
            'doc_ids': docs.ids,
            'doc_model': 'room.booking',
            'docs': docs,
        }
