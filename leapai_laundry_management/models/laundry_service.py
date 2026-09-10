from odoo import models, fields


class LaundryService(models.Model):
    _name = 'laundry.service'
    _description = 'Laundry Service'
    _order = 'sequence, name'

    name = fields.Char(string='Service Name', required=True)
    service_type = fields.Selection([
        ('wash', 'Washing Service'),
        ('extra', 'Extra Service'),
    ], string='Type', required=True, default='wash')
    sequence = fields.Integer(default=10)
    price = fields.Float(string='Default Price')
    product_id = fields.Many2one('product.product', string='Invoice Product')
    description = fields.Text(string='Description')
    active = fields.Boolean(default=True)
    color = fields.Integer(string='Color')
