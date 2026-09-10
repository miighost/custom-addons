from odoo import models, fields, api


class LaundryOrderLine(models.Model):
    _name = 'laundry.order.line'
    _description = 'Laundry Order Line'
    _order = 'sequence, id'

    order_id = fields.Many2one('laundry.order', string='Order', ondelete='cascade')
    sequence = fields.Integer(default=10)
    cloth_type_id = fields.Many2one('laundry.cloth.type', string='Cloth Type', required=True)
    size_id = fields.Many2one('laundry.cloth.size', string='Size')
    service_id = fields.Many2one('laundry.service', string='Washing Service', required=True,
        domain=[('service_type', '=', 'wash')])
    extra_service_ids = fields.Many2many('laundry.service', 'order_line_extra_service_rel',
        'line_id', 'service_id', string='Extra Services',
        domain=[('service_type', '=', 'extra')])
    qty = fields.Float(string='Quantity', default=1.0)
    washing_price = fields.Float(string='Wash Price / Unit')
    extra_price = fields.Float(string='Extra Price / Unit', compute='_compute_extra_price', store=True)
    washing_subtotal = fields.Monetary(string='Wash Subtotal', compute='_compute_subtotals', store=True,
        currency_field='currency_id')
    extra_subtotal = fields.Monetary(string='Extra Subtotal', compute='_compute_subtotals', store=True,
        currency_field='currency_id')
    subtotal = fields.Monetary(string='Subtotal', compute='_compute_subtotals', store=True,
        currency_field='currency_id')
    currency_id = fields.Many2one(related='order_id.currency_id', store=True)
    notes = fields.Text(string='Special Instructions')
    state = fields.Selection(related='order_id.state', string='Order State', store=True)

    @api.onchange('cloth_type_id')
    def _onchange_cloth_type(self):
        if self.cloth_type_id and self.cloth_type_id.default_size_id:
            self.size_id = self.cloth_type_id.default_size_id

    @api.onchange('service_id')
    def _onchange_service(self):
        if self.service_id:
            self.washing_price = self.service_id.price

    @api.depends('extra_service_ids', 'extra_service_ids.price')
    def _compute_extra_price(self):
        for line in self:
            line.extra_price = sum(line.extra_service_ids.mapped('price'))

    @api.depends('qty', 'washing_price', 'extra_price')
    def _compute_subtotals(self):
        for line in self:
            line.washing_subtotal = line.qty * line.washing_price
            line.extra_subtotal = line.qty * line.extra_price
            line.subtotal = line.washing_subtotal + line.extra_subtotal
