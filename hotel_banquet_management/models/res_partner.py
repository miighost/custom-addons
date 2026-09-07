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
from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    is_banquet_customer = fields.Boolean(
        string='Banquet Customer',
        compute='_compute_is_banquet_customer',
        search='_search_is_banquet_customer',
        help="Whether this customer has banquet bookings or events."
    )
    banquet_count = fields.Integer(
        string='Banquet Bookings',
        compute='_compute_banquet_count',
        help="Number of banquet and event orders for this customer."
    )

    def _compute_banquet_count(self):
        for partner in self:
            partner.banquet_count = self.env['sale.order'].search_count([
                ('partner_id', 'child_of', partner.id),
                ('is_banquet', '=', True)
            ])

    @api.depends('sale_order_ids.is_banquet')
    def _compute_is_banquet_customer(self):
        for partner in self:
            partner.is_banquet_customer = partner.banquet_count > 0

    def _search_is_banquet_customer(self, operator, value):
        order_partner_ids = self.env['sale.order'].search([
            ('is_banquet', '=', True)
        ]).mapped('partner_id').ids
        flaad_partner_ids = []
        if 'banquet.flaad.quotation' in self.env:
            flaad_partner_ids = self.env['banquet.flaad.quotation'].search([]).mapped('partner_id').ids
        all_partner_ids = list(set(order_partner_ids + flaad_partner_ids))
        positive = (operator in ('=', '!=') and ((operator == '=' and bool(value)) or (operator == '!=' and not bool(value))))
        if positive:
            return [('id', 'in', all_partner_ids)]
        else:
            return [('id', 'not in', all_partner_ids)]

    def action_view_banquet_orders(self):
        self.ensure_one()
        action = self.env.ref('hotel_banquet_management.action_banquet_orders').read()[0]
        action['domain'] = [('partner_id', 'child_of', self.id), ('is_banquet', '=', True)]
        action['context'] = {'default_partner_id': self.id, 'default_is_banquet': 1}
        return action
