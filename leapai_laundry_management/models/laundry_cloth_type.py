from odoo import models, fields


class LaundryClothType(models.Model):
    _name = 'laundry.cloth.type'
    _description = 'Cloth Type'
    _order = 'sequence, name'

    name = fields.Char(string='Cloth Type', required=True)
    sequence = fields.Integer(default=10)
    default_size_id = fields.Many2one('laundry.cloth.size', string='Default Size')
    notes = fields.Text(string='Notes')
    active = fields.Boolean(default=True)
    image = fields.Image(string='Image', max_width=128, max_height=128)
