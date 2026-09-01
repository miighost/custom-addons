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
from odoo import fields, models


class BanquetVenue(models.Model):
    _name = 'banquet.venue'
    _description = 'Banquet Venue / Hall'
    _order = 'name'

    name = fields.Char(string='Venue / Hall Name', required=True)
    code = fields.Char(string='Code', size=10)
    capacity_min = fields.Integer(string='Min Capacity (Pax)', default=10)
    capacity_max = fields.Integer(string='Max Capacity (Pax)', default=500)
    location = fields.Char(string='Location / Floor')
    description = fields.Text(string='Description / Features')
    active = fields.Boolean(string='Active', default=True)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)
