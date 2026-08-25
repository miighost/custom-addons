# -*- coding: utf-8 -*-
from odoo import api, models


class ReportSaleOrder(models.AbstractModel):
    """Abstract model for generating the Sale Order QWeb PDF Report."""

    _name = 'report.hotel_management_odoo.report_sale_order'
    _description = 'Sale Order Report Parser'

    @api.model
    def _get_report_values(self, docids, data=None):
        """Handle printing both from Wizard (with data) and directly from Form View (docids)."""
        if data and data.get('booking'):
            booking_lines = data['booking']
        else:
            docs = self.env['room.booking'].browse(docids) if docids else self.env['room.booking'].search([])
            booking_lines = []
            for rec in docs:
                partner_name = rec.partner_id.name if rec.partner_id else '-'
                booking_lines.append({
                    'partner_id': partner_name,
                    'checkin_date': rec.checkin_date,
                    'checkout_date': rec.checkout_date,
                    'name': rec.name,
                    'amount_total': rec.amount_total,
                })

        return {
            'doc_ids': docids,
            'doc_model': 'room.booking',
            'booking': booking_lines,
        }
