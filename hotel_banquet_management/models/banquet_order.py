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
from odoo.tools.misc import formatLang


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
            if vals.get('is_banquet') or self.env.context.get('default_is_banquet') or vals.get('banquet_venue_id') or vals.get('event_type_id') or vals.get('event_name'):
                vals['is_banquet'] = True
                if vals.get('name', _('New')) in (_('New'), False, '/'):
                    vals['name'] = self.env['ir.sequence'].next_by_code('banquet.quotation') or _('New')
        return super(BanquetSaleOrder, self.with_context(
            mail_create_nosubscribe=True,
            mail_create_nolog=True,
            mail_notrack=True,
        )).create(vals_list)

    def write(self, vals):
        if self.env.context.get('default_is_banquet') or any(k in vals for k in ('banquet_venue_id', 'event_type_id', 'event_name')):
            vals['is_banquet'] = True
        return super().write(vals)

    @api.depends('order_line.price_subtotal', 'order_line.price_tax', 'order_line.price_total', 'order_line.number_of_days')
    def _compute_amounts(self):
        """Synchronize Untaxed Amount, Taxes and Total Amount with Banquet multi-day line subtotals."""
        super()._compute_amounts()
        for order in self:
            is_banquet = order.is_banquet or self.env.context.get('default_is_banquet') or any((l.number_of_days or 1.0) > 1.0 for l in order.order_line)
            if is_banquet:
                order_lines = order.order_line.filtered(lambda x: not x.display_type)
                order.amount_untaxed = sum(order_lines.mapped('price_subtotal'))
                order.amount_tax = sum(order_lines.mapped('price_tax'))
                order.amount_total = order.amount_untaxed + order.amount_tax

    @api.depends('order_line.price_subtotal', 'order_line.price_tax', 'order_line.price_total', 'order_line.number_of_days', 'order_line.product_uom_qty', 'order_line.price_unit')
    def _compute_tax_totals(self):
        """Ensure the tax_totals widget on the form displays the exact multi-day calculation."""
        super()._compute_tax_totals()
        for order in self:
            is_banquet = order.is_banquet or self.env.context.get('default_is_banquet') or any((l.number_of_days or 1.0) > 1.0 for l in order.order_line)
            if is_banquet and order.tax_totals:
                lines = order.order_line.filtered(lambda x: not x.display_type)
                untaxed = sum(lines.mapped('price_subtotal'))
                tax = sum(lines.mapped('price_tax'))
                total = untaxed + tax
                currency = order.currency_id or order.company_id.currency_id

                formatted_untaxed = formatLang(order.env, untaxed, currency_obj=currency)
                formatted_tax = formatLang(order.env, tax, currency_obj=currency)
                formatted_total = formatLang(order.env, total, currency_obj=currency)

                tax_totals = dict(order.tax_totals)
                orig_untaxed = tax_totals.get('amount_untaxed') or 1.0
                ratio = untaxed / orig_untaxed if orig_untaxed else 1.0

                tax_totals['amount_untaxed'] = untaxed
                tax_totals['amount_total'] = total
                tax_totals['formatted_amount_untaxed'] = formatted_untaxed
                tax_totals['formatted_amount_total'] = formatted_total

                if 'subtotals' in tax_totals and tax_totals['subtotals']:
                    for sub in tax_totals['subtotals']:
                        sub['amount'] = untaxed
                        sub['formatted_amount'] = formatted_untaxed

                if 'groups_by_subtotal' in tax_totals and tax_totals['groups_by_subtotal']:
                    for sub_name, groups in tax_totals['groups_by_subtotal'].items():
                        for g in groups:
                            new_group_amount = g.get('tax_group_amount', 0.0) * ratio
                            new_base_amount = g.get('tax_group_base_amount', 0.0) * ratio
                            g['tax_group_amount'] = new_group_amount
                            g['tax_group_base_amount'] = new_base_amount
                            g['formatted_tax_group_amount'] = formatLang(order.env, new_group_amount, currency_obj=currency)
                            g['formatted_tax_group_base_amount'] = formatLang(order.env, new_base_amount, currency_obj=currency)

                order.tax_totals = tax_totals

    def _send_order_confirmation_mail(self):
        """Prevent synchronous SMTP network delays when confirming banquet orders."""
        banquet_orders = self.filtered(lambda o: o.is_banquet or self.env.context.get('default_is_banquet'))
        other_orders = self - banquet_orders
        if other_orders:
            super(BanquetSaleOrder, other_orders)._send_order_confirmation_mail()
        return True

    def action_confirm(self):
        """Instant confirmation without stock picking delays or mail timeouts."""
        for order in self:
            if order.is_banquet or self.env.context.get('default_is_banquet') or order.banquet_venue_id or order.event_name:
                order.is_banquet = True
                if order.name and ('QUOT/' in order.name or order.name.startswith('QUOT') or order.name.startswith('S')):
                    new_seq = self.env['ir.sequence'].next_by_code('banquet.order')
                    if new_seq:
                        order.name = new_seq
        return super(BanquetSaleOrder, self.with_context(
            mail_notrack=True,
            mail_create_nosubscribe=True,
            mail_notify_author=False,
            mail_post_autofollow=False,
            skip_procurement=True,
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
        self._compute_amount()

    @api.depends('product_id', 'product_uom_qty')
    def _compute_price_unit(self):
        """Preserve user-entered unit price when changing quantity or number of days."""
        for line in self:
            is_banquet = line.order_id.is_banquet or self.env.context.get('default_is_banquet') or ((line.number_of_days or 1.0) > 1.0)
            if is_banquet and line.price_unit and line.product_id:
                continue
            super(BanquetSaleOrderLine, line)._compute_price_unit()

    @api.depends('product_uom_qty', 'number_of_days', 'discount', 'price_unit', 'tax_ids')
    def _compute_amount(self):
        """Calculate line amounts including Number of Days: Qty * No of Days * Unit Price"""
        super()._compute_amount()
        for line in self:
            days = line.number_of_days if (line.number_of_days and line.number_of_days > 0) else 1.0
            is_banquet = line.order_id.is_banquet or self.env.context.get('default_is_banquet') or (days > 1.0)
            if is_banquet and days > 1.0:
                effective_qty = (line.product_uom_qty or 0.0) * days
                price = (line.price_unit or 0.0) * (1 - (line.discount or 0.0) / 100.0)
                taxes_field = getattr(line, 'tax_ids', False) or getattr(line, 'tax_id', False)
                if taxes_field:
                    taxes = taxes_field.compute_all(
                        price,
                        line.order_id.currency_id or line.currency_id,
                        effective_qty,
                        product=line.product_id,
                        partner=line.order_id.partner_shipping_id
                    )
                    line.price_tax = sum(t.get('amount', 0.0) for t in taxes.get('taxes', []))
                    line.price_total = taxes['total_included']
                    line.price_subtotal = taxes['total_excluded']
                else:
                    subtotal = price * effective_qty
                    line.price_tax = 0.0
                    line.price_total = subtotal
                    line.price_subtotal = subtotal

    def _prepare_tax_base_line_dict(self, **kwargs):
        """Pass effective quantity to Odoo native tax computation."""
        res = super()._prepare_tax_base_line_dict(**kwargs) if hasattr(super(), '_prepare_tax_base_line_dict') else {}
        days = self.number_of_days if (self.number_of_days and self.number_of_days > 0) else 1.0
        is_banquet = self.order_id.is_banquet or self.env.context.get('default_is_banquet') or (days > 1.0)
        if is_banquet and days > 1.0:
            res['quantity'] = (self.product_uom_qty or 0.0) * days
            if 'price_subtotal' in res:
                res['price_subtotal'] = self.price_subtotal
        return res

    def _action_launch_stock_rule(self, previous_product_uom_qty=False):
        """Banquet service orders should not trigger warehouse delivery pickings or reservation delays."""
        banquet_lines = self.filtered(lambda l: l.order_id.is_banquet or self.env.context.get('default_is_banquet'))
        other_lines = self - banquet_lines
        if other_lines:
            return super(BanquetSaleOrderLine, other_lines)._action_launch_stock_rule(previous_product_uom_qty=previous_product_uom_qty)
        return True

    def _prepare_invoice_line(self, **optional_values):
        """Propagate quantity and number_of_days cleanly to invoice line."""
        res = super()._prepare_invoice_line(**optional_values)
        days = self.number_of_days if (self.number_of_days and self.number_of_days > 0) else 1.0
        is_banquet = self.order_id.is_banquet or self.env.context.get('default_is_banquet') or (days > 1.0)
        if is_banquet:
            res['number_of_days'] = days
            res['quantity'] = self.qty_to_invoice or self.product_uom_qty
            res['price_unit'] = self.price_unit
        return res
