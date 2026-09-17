# -*- coding: utf-8 -*-
#############################################################################
#
#    Cybrosys Technologies Pvt. Ltd.
#
#    Copyright (C) 2026-TODAY Cybrosys Technologies(<https://www.cybrosys.com>)
#    Author: Cybrosys Techno Solutions(<https://www.cybrosys.com>)
#
#    You can modify it under the terms of the GNU LESSER
#    GENERAL PUBLIC LICENSE (LGPL v3), Version 3.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU LESSER GENERAL PUBLIC LICENSE (LGPL v3) for more details.
#
#    You should have received a copy of the GNU LESSER GENERAL PUBLIC LICENSE
#    (LGPL v3) along with this program.
#    If not, see <http://www.gnu.org/licenses/>.
#
#############################################################################
from odoo import fields, models


class HotelFloor(models.Model):
    """Model that holds the Hotel Floors."""
    _name = "hotel.floor"
    _description = "Floor"
    _order = 'id desc'

    def _auto_init(self):
        super()._auto_init()
        # Backfill company_id for existing floors safely during upgrade
        self.env.cr.execute("""
            UPDATE hotel_floor
            SET company_id = (SELECT id FROM res_company ORDER BY id ASC LIMIT 1)
            WHERE company_id IS NULL;
        """)

    name = fields.Char(string="Name", help="Name of the floor", required=True)
    company_id = fields.Many2one('res.company', string='Company',
                                 default=lambda self: self.env.company,
                                 index=True)
    user_id = fields.Many2one('res.users', string='Manager',
                              help="Manager of the Floor",
                              required=True)