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
#############################################################################
from odoo import _, api, fields, models


def _default_banquet_terms(self=None):
    return """
<div style="font-family: inherit; font-size: 13px; color: #333;">
    <h4 style="font-weight: bold; margin-bottom: 6px;">Banquet &amp; Event Terms and Conditions:</h4>
    <ol style="margin-left: 20px; padding-left: 0; line-height: 1.6;">
        <li><strong>Booking &amp; Confirmation:</strong> A 50% deposit is required upon confirmation to secure the date and venue.</li>
        <li><strong>Final Payment:</strong> The remaining balance must be cleared at least 48 hours prior to the event start.</li>
        <li><strong>Cancellation Policy:</strong> Cancellations made within 7 days of the event are subject to a 50% cancellation fee.</li>
        <li><strong>Event Timings:</strong> The hall is booked for the specified duration. Additional hours will incur extra charges.</li>
        <li><strong>Damage &amp; Liability:</strong> The client is responsible for any damage caused to hotel property or equipment during the event.</li>
    </ol>
</div>
"""


class BanquetSaleOrder(models.Model):
    _inherit = 'sale.order'

    is_banquet = fields.Boolean(
        string='Is Banquet',
        default=False,
        copy=False,
        index=True,
        help="Check this if this order is a Banquet/Event booking."
    )
    event_name = fields.Char(
        string='Event / Function Name',
        copy=False,
        help="e.g. Wedding Reception, Corporate Seminar, Annual Gala Dinner"
    )
    event_type_id = fields.Many2one(
        'banquet.event.type',
        string='Event Type',
        ondelete='restrict'
    )
    event_start_date = fields.Datetime(
        string='Event Start Date & Time',
        copy=False
    )
    event_end_date = fields.Datetime(
        string='Event End Date & Time',
        copy=False
    )
    guest_count = fields.Integer(
        string='Guests / Pax',
        default=50,
        help="Expected number of attendees."
    )
    banquet_venue_id = fields.Many2one(
        'banquet.venue',
        string='Venue / Hall',
        ondelete='restrict'
    )
    terms_and_conditions = fields.Html(
        string='Terms and Conditions',
        default=_default_banquet_terms,
        copy=True
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('is_banquet') or self.env.context.get('default_is_banquet'):
                vals['is_banquet'] = True
                if vals.get('name', _('New')) in (_('New'), False, '/'):
                    vals['name'] = self.env['ir.sequence'].next_by_code('banquet.quotation') or _('New')
        return super().create(vals_list)

    def action_confirm(self):
        """When confirming a banquet quotation, assign BO/... sequence if still on QUOT/..."""
        res = super().action_confirm()
        for order in self:
            if order.is_banquet:
                if order.name and ('QUOT/' in order.name or order.name.startswith('QUOT')):
                    new_seq = self.env['ir.sequence'].next_by_code('banquet.order')
                    if new_seq:
                        order.write({'name': new_seq})
        return res

    def action_print_banquet_quotation(self):
        self.ensure_one()
        return self.env.ref('hotel_banquet_management.action_report_banquet_order').report_action(self)

    def action_print_banquet_order(self):
        self.ensure_one()
        return self.env.ref('hotel_banquet_management.action_report_banquet_order').report_action(self)


class BanquetSaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    number_of_days = fields.Float(
        string='No of Days',
        default=1.0,
        digits='Product Unit of Measure',
        help="Number of days or sessions for this service."
    )

    @api.depends('product_uom_qty', 'number_of_days', 'discount', 'price_unit', 'tax_ids')
    def _compute_amount(self):
        """Calculate line amounts including Number of Days: Qty * No of Days * Unit Price"""
        super()._compute_amount()
        for line in self:
            if line.order_id.is_banquet:
                days = line.number_of_days if line.number_of_days > 0 else 1.0
                effective_qty = line.product_uom_qty * days
                price = line.price_unit * (1 - (line.discount or 0.0) / 100.0)
                taxes_field = getattr(line, 'tax_ids', False) or getattr(line, 'tax_id', False)
                if taxes_field:
                    taxes = taxes_field.compute_all(
                        price,
                        line.order_id.currency_id,
                        effective_qty,
                        product=line.product_id,
                        partner=line.order_id.partner_shipping_id
                    )
                    line.update({
                        'price_tax': sum(t.get('amount', 0.0) for t in taxes.get('taxes', [])),
                        'price_total': taxes['total_included'],
                        'price_subtotal': taxes['total_excluded'],
                    })
                else:
                    subtotal = price * effective_qty
                    line.update({
                        'price_tax': 0.0,
                        'price_total': subtotal,
                        'price_subtotal': subtotal,
                    })

    def _prepare_invoice_line(self, **optional_values):
        """Propagate number_of_days and adjust quantity so standard Odoo invoices calculate accurately."""
        res = super()._prepare_invoice_line(**optional_values)
        if self.order_id.is_banquet:
            days = self.number_of_days if self.number_of_days > 0 else 1.0
            res['number_of_days'] = days
            # Set invoice line quantity to total billable units (qty * days) to ensure invoice subtotal matches order
            res['quantity'] = (self.qty_to_invoice or self.product_uom_qty) * days
        return res
