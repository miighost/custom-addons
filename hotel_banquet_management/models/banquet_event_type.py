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


class BanquetEventType(models.Model):
    _name = 'banquet.event.type'
    _description = 'Banquet Event Type'
    _order = 'name'

    name = fields.Char(string='Event Type', required=True, translate=True)
    code = fields.Char(string='Code', size=10)
    description = fields.Text(string='Description')
    active = fields.Boolean(string='Active', default=True)
