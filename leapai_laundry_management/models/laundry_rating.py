from odoo import models, fields


class LaundryRating(models.Model):
    _name = 'laundry.rating'
    _description = 'Laundry Rating'
    _order = 'date desc'

    order_id = fields.Many2one('laundry.order', string='Laundry Order', required=True, ondelete='cascade')
    customer_id = fields.Many2one(related='order_id.customer_id', string='Customer', store=True)
    date = fields.Datetime(string='Date', default=fields.Datetime.now)
    rating = fields.Selection([
        ('good', 'Good'),
        ('average', 'Average'),
        ('bad', 'Bad'),
    ], string='Rating', required=True)
    review = fields.Text(string='Customer Review')
    notes = fields.Text(string='Internal Notes')
