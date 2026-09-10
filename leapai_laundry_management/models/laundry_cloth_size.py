from odoo import models, fields


class LaundryClothSize(models.Model):
    _name = 'laundry.cloth.size'
    _description = 'Cloth Size'
    _order = 'sequence, name'

    name = fields.Char(string='Size', required=True)
    code = fields.Char(string='Code')
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
