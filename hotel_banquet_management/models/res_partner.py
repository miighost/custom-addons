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

    def action_view_banquet_orders(self):
        self.ensure_one()
        action = self.env.ref('hotel_banquet_management.action_banquet_orders').read()[0]
        action['domain'] = [('partner_id', 'child_of', self.id), ('is_banquet', '=', True)]
        action['context'] = {'default_partner_id': self.id, 'default_is_banquet': 1}
        return action
