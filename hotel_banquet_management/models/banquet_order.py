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

    @api.depends('order_line.price_subtotal', 'order_line.price_tax', 'order_line.price_total', 'order_line.number_of_days')
    def _compute_amounts(self):
        """Synchronize Untaxed Amount, Taxes and Total Amount with Banquet multi-day line subtotals."""
        super()._compute_amounts()
        for order in self:
            if order.is_banquet:
                order_lines = order.order_line.filtered(lambda x: not x.display_type)
                order.amount_untaxed = sum(order_lines.mapped('price_subtotal'))
                order.amount_tax = sum(order_lines.mapped('price_tax'))
                order.amount_total = order.amount_untaxed + order.amount_tax

    @api.depends('order_line.price_subtotal', 'order_line.number_of_days', 'order_line.price_unit', 'order_line.product_uom_qty')
    def _compute_tax_totals(self):
        """Ensure the tax_totals widget on the form displays the exact multi-day calculation."""
        super()._compute_tax_totals()
        for order in self:
            if order.is_banquet and order.tax_totals:
                order_lines = order.order_line.filtered(lambda x: not x.display_type)
                untaxed = sum(order_lines.mapped('price_subtotal'))
                tax = sum(order_lines.mapped('price_tax'))
                total = untaxed + tax
                tax_totals = dict(order.tax_totals)
                tax_totals['amount_untaxed'] = untaxed
                tax_totals['amount_total'] = total
                if 'subtotals' in tax_totals and tax_totals['subtotals']:
                    for sub in tax_totals['subtotals']:
                        sub['amount'] = untaxed
                order.tax_totals = tax_totals

    def action_confirm(self):
        """Instant confirmation without stock picking delays or mail timeouts."""
        for order in self:
            if order.is_banquet:
                if order.name and ('QUOT/' in order.name or order.name.startswith('QUOT')):
                    new_seq = self.env['ir.sequence'].next_by_code('banquet.order')
                    if new_seq:
                        order.name = new_seq
        return super(BanquetSaleOrder, self.with_context(
            mail_notrack=True,
            mail_create_nosubscribe=True,
            mail_notify_author=False,
            mail_post_autofollow=False,
        )).action_confirm()

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

    @api.onchange('number_of_days')
    def _onchange_number_of_days(self):
        """Trigger immediate recalculation in the UI when typing No of Days."""
        if self.order_id.is_banquet:
            self._compute_amount()

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

    def _convert_to_tax_base_line_dict(self, **kwargs):
        """Pass effective quantity (product_uom_qty * number_of_days) to Odoo tax computation."""
        res = super()._convert_to_tax_base_line_dict(**kwargs)
        if self.order_id.is_banquet:
            days = self.number_of_days if self.number_of_days > 0 else 1.0
            res['quantity'] = self.product_uom_qty * days
            if 'price_subtotal' in res:
                res['price_subtotal'] = self.price_subtotal
        return res

    def _action_launch_stock_rule(self, previous_product_uom_qty=False):
        """Banquet service orders should not trigger warehouse delivery pickings or reservation delays."""
        banquet_lines = self.filtered(lambda l: l.order_id.is_banquet)
        other_lines = self - banquet_lines
        if other_lines:
            return super(BanquetSaleOrderLine, other_lines)._action_launch_stock_rule(previous_product_uom_qty=previous_product_uom_qty)
        return True

    def _prepare_invoice_line(self, **optional_values):
        """Propagate quantity and number_of_days cleanly to invoice line."""
        res = super()._prepare_invoice_line(**optional_values)
        if self.order_id.is_banquet:
            days = self.number_of_days if self.number_of_days > 0 else 1.0
            res['number_of_days'] = days
            res['quantity'] = self.qty_to_invoice or self.product_uom_qty
        return res
