from odoo import fields, models


class AppApiEndpoint(models.Model):
    _name = 'app.api.endpoint'
    _description = 'Mobile App API Endpoint'
    _order = 'sequence, category, name'

    name = fields.Char(string='Endpoint Name', required=True, translate=True)
    sequence = fields.Integer(string='Sequence', default=10)
    route = fields.Char(string='Route / Path', required=True, index=True,
                        help="The relative URL path of the API endpoint, e.g. /api/v1/menu")
    method = fields.Selection([
        ('POST', 'POST'),
        ('GET', 'GET'),
        ('PUT', 'PUT'),
        ('DELETE', 'DELETE'),
    ], string='HTTP Method', default='POST', required=True)
    category = fields.Selection([
        ('bootstrap', 'Bootstrap & Init'),
        ('catalogue', 'Catalogue & Products'),
        ('pos', 'Point of Sale & Tables'),
        ('orders', 'Orders & Checkout'),
        ('wallet', 'eWallet & Top-Up'),
        ('allowance', 'Staff Allowance'),
        ('account', 'Account & Invoices'),
        ('profile', 'User Profile'),
    ], string='Category', default='catalogue', required=True, index=True)
    active = fields.Boolean(
        string='Active', default=True,
        help="Toggle off to temporarily disable or archive this endpoint.")
    auth_type = fields.Selection([
        ('bearer', 'Firebase Bearer Token'),
        ('public', 'Public (No Token)'),
    ], string='Authentication', default='bearer', required=True)
    model_ids = fields.Many2many(
        'ir.model', string='Allowed / Target Models',
        help="Odoo models queried or modified by this endpoint.")
    description = fields.Text(string='Description & Business Rules')
    sample_request = fields.Text(string='Sample Request Payload')
    sample_response = fields.Text(string='Sample Response Payload')
    error_codes = fields.Text(string='Error Codes & Troubleshooting')
