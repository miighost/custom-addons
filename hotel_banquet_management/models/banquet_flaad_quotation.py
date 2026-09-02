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
from .banquet_order import _default_banquet_terms


class BanquetFlaadQuotation(models.Model):
    _name = 'banquet.flaad.quotation'
    _description = 'Flaad Quotation (Draft Simulation - No Database/Accounting Impact)'
    _order = 'id desc'

    name = fields.Char(
        string='Quote Reference',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('New')
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Customer / Company',
        required=True,
        domain="['|', ('is_company', '=', True), ('customer_rank', '>', 0)]"
    )
    event_name = fields.Char(
        string='Event / Function Name',
        placeholder="e.g. Wedding Reception, Corporate Dinner, Conference"
    )
    event_type_id = fields.Many2one(
        'banquet.event.type',
        string='Event Type'
    )
    banquet_venue_id = fields.Many2one(
        'banquet.venue',
        string='Venue / Hall'
    )
    event_start_date = fields.Datetime(string='Start Date & Time')
    event_end_date = fields.Datetime(string='End Date & Time')
    guest_count = fields.Integer(string='Guests / Pax', default=50)
    date_order = fields.Date(string='Quote Date', default=fields.Date.context_today)

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='company_id.currency_id',
        string='Currency',
        readonly=True
    )
    user_id = fields.Many2one(
        'res.users',
        string='Prepared By',
        default=lambda self: self.env.user
    )

    line_ids = fields.One2many(
        'banquet.flaad.quotation.line',
        'quotation_id',
        string='Quotation Lines',
        copy=True
    )

    amount_untaxed = fields.Monetary(
        string='Untaxed Amount',
        compute='_compute_amounts',
        store=True,
        currency_field='currency_id'
    )
    amount_tax = fields.Monetary(
        string='Taxes',
        compute='_compute_amounts',
        store=True,
        currency_field='currency_id'
    )
    amount_total = fields.Monetary(
        string='Total Amount',
        compute='_compute_amounts',
        store=True,
        currency_field='currency_id'
    )

    note = fields.Text(string='Customer Notes')
    terms_and_conditions = fields.Html(
        string='Terms and Conditions',
        default=_default_banquet_terms,
        copy=True
    )

    state = fields.Selection([
        ('draft', 'Draft'),
        ('sent', 'Sent / Printed'),
        ('converted', 'Converted to Real Order'),
        ('cancel', 'Cancelled')
    ], string='Status', default='draft', copy=False)

    real_sale_order_id = fields.Many2one(
        'sale.order',
        string='Real Banquet Order',
        readonly=True,
        copy=False
    )

    @api.depends('line_ids.price_subtotal', 'line_ids.price_tax', 'line_ids.price_total')
    def _compute_amounts(self):
        for rec in self:
            rec.amount_untaxed = sum(rec.line_ids.mapped('price_subtotal'))
            rec.amount_tax = sum(rec.line_ids.mapped('price_tax'))
            rec.amount_total = rec.amount_untaxed + rec.amount_tax

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) in (_('New'), False, '/'):
                vals['name'] = self.env['ir.sequence'].next_by_code('banquet.flaad.quotation') or _('New')
        return super().create(vals_list)

    def action_send(self):
        self.ensure_one()
        self.state = 'sent'

    def action_cancel(self):
        self.ensure_one()
        self.state = 'cancel'

    def action_draft(self):
        self.ensure_one()
        self.state = 'draft'

    def action_print(self):
        self.ensure_one()
        if self.state == 'draft':
            self.state = 'sent'
        return self.env.ref('hotel_banquet_management.action_report_banquet_flaad_quotation').report_action(self)

    def action_convert_to_real_order(self):
        """Convert this Flaad simulation quote into an official Banquet Quotation."""
        self.ensure_one()
        sale_order = self.env['sale.order'].create({
            'is_banquet': True,
            'partner_id': self.partner_id.id,
            'event_name': self.event_name,
            'event_type_id': self.event_type_id.id if self.event_type_id else False,
            'banquet_venue_id': self.banquet_venue_id.id if self.banquet_venue_id else False,
            'event_start_date': self.event_start_date,
            'event_end_date': self.event_end_date,
            'guest_count': self.guest_count,
            'company_id': self.company_id.id,
            'note': self.note,
            'terms_and_conditions': self.terms_and_conditions,
            'order_line': [
                (0, 0, {
                    'product_id': line.product_id.id,
                    'name': line.name,
                    'product_uom_qty': line.product_uom_qty,
                    'number_of_days': line.number_of_days,
                    'price_unit': line.price_unit,
                    'discount': line.discount,
                    'tax_ids': [(6, 0, line.tax_ids.ids)],
                }) for line in self.line_ids
            ]
        })
        self.write({
            'state': 'converted',
            'real_sale_order_id': sale_order.id
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Real Banquet Quotation'),
            'res_model': 'sale.order',
            'res_id': sale_order.id,
            'view_mode': 'form',
            'target': 'current',
        }


class BanquetFlaadQuotationLine(models.Model):
    _name = 'banquet.flaad.quotation.line'
    _description = 'Flaad Quotation Line'

    quotation_id = fields.Many2one(
        'banquet.flaad.quotation',
        string='Quotation',
        required=True,
        ondelete='cascade'
    )
    product_id = fields.Many2one(
        'product.product',
        string='Product / Service',
        required=True,
        domain="[('sale_ok', '=', True)]"
    )
    name = fields.Text(string='Description', required=True)
    product_uom_qty = fields.Float(string='Qty', default=1.0)
    number_of_days = fields.Float(string='No of Days', default=1.0)
    price_unit = fields.Float(string='Unit Price', digits='Product Price', default=0.0)
    discount = fields.Float(string='Disc.%', default=0.0)
    tax_ids = fields.Many2many('account.tax', string='Taxes')

    currency_id = fields.Many2one(
        'res.currency',
        related='quotation_id.currency_id',
        string='Currency',
        readonly=True
    )
    price_subtotal = fields.Monetary(
        string='Subtotal',
        compute='_compute_amount',
        store=True,
        currency_field='currency_id'
    )
    price_tax = fields.Monetary(
        string='Tax Amount',
        compute='_compute_amount',
        store=True,
        currency_field='currency_id'
    )
    price_total = fields.Monetary(
        string='Total',
        compute='_compute_amount',
        store=True,
        currency_field='currency_id'
    )

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.name = self.product_id.get_product_multiline_description_sale() if hasattr(self.product_id, 'get_product_multiline_description_sale') else self.product_id.display_name
            self.price_unit = self.product_id.list_price
            self.tax_ids = self.product_id.taxes_id

    @api.depends('product_uom_qty', 'number_of_days', 'price_unit', 'discount', 'tax_ids')
    def _compute_amount(self):
        for line in self:
            days = line.number_of_days if line.number_of_days > 0 else 1.0
            effective_qty = line.product_uom_qty * days
            price = line.price_unit * (1 - (line.discount or 0.0) / 100.0)
            if line.tax_ids:
                taxes = line.tax_ids.compute_all(
                    price,
                    line.quotation_id.currency_id,
                    effective_qty,
                    product=line.product_id,
                    partner=line.quotation_id.partner_id
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
