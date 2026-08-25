# -*- coding: utf-8 -*-
from odoo import api, models


class ReportReservationAcknowledgement(models.AbstractModel):
    """Abstract model for generating Reservation Acknowledgement QWeb PDF Report."""

    _name = 'report.hotel_management_odoo.report_reservation_acknowledgement'
    _description = 'Reservation Acknowledgement Report Parser'

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env['room.booking'].browse(docids)
        plan_labels = {
            'bb': 'Bed & Breakfast (BB)',
            'hb': 'Half Board (HB)',
            'fb': 'Full Board (FB)',
            'ro': 'Room Only (RO)',
        }
        return {
            'doc_ids': docids,
            'doc_model': 'room.booking',
            'docs': docs,
            'plan_labels': plan_labels,
        }
