from odoo import fields, models


class RestaurantTable(models.Model):
    _inherit = 'restaurant.table'

    table_name = fields.Char(
        string='Table Name / Label',
        help="Custom friendly name shown on the mobile app and POS receipts (e.g. 'VIP Booth', 'Window Table 1', 'Terrace 4'). If left blank, defaults to 'Table <number>'."
    )
