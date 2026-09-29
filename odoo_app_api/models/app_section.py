from odoo import api, fields, models


class AppSection(models.Model):
    _name = 'app.section'
    _description = 'Mobile App Curated Section'
    _order = 'sequence, id'

    name = fields.Char(string='Section Title', required=True, translate=True)
    code = fields.Char(
        string='Code / Identifier', required=True, index=True,
        help="Technical identifier used by FlutterFlow or API filters (e.g. todays_best, most_recent, featured, special_offers).")
    subtitle = fields.Char(string='Subtitle / Description', translate=True)
    badge_text = fields.Char(string='Badge / Ribbon Text', help="e.g. 'HOT', 'NEW', 'SAVE 20%', 'CHEF PICK'.")
    sequence = fields.Integer(string='Sequence', default=10, help="Display order in the mobile app.")
    active = fields.Boolean(string='Active', default=True)
    color = fields.Integer(string='Color Index', default=0)

    mode = fields.Selection([
        ('manual', 'Manual Product Selection'),
        ('recent', 'Most Recent Products (Automatic)'),
    ], string='Selection Mode', default='manual', required=True)

    product_ids = fields.Many2many(
        'product.product',
        'app_section_product_rel',
        'section_id', 'product_id',
        string='Selected Products',
        domain=[('sale_ok', '=', True)],
        help="Select products to appear under this section in the mobile app.")

    product_count = fields.Integer(compute='_compute_product_count', string='Products Count')

    banner_image = fields.Image(
        string='Banner Image', max_width=1024, max_height=512,
        help="Optional promo banner / ad image displayed above this section in the app.")
    has_banner = fields.Boolean(compute='_compute_banner_info', string='Has Banner')
    banner_url = fields.Char(compute='_compute_banner_info', string='Banner URL')

    date_start = fields.Datetime(string='Start Date', help="Optional: show section only starting from this date/time.")
    date_end = fields.Datetime(string='End Date', help="Optional: hide section automatically after this date/time.")

    @api.depends('product_ids', 'mode')
    def _compute_product_count(self):
        for rec in self:
            if rec.mode == 'recent':
                domain = [('sale_ok', '=', True), ('active', '=', True), ('available_in_app', '=', True)]
                rec.product_count = self.env['product.product'].sudo().search_count(domain)
            else:
                rec.product_count = len(rec.product_ids)

    def _get_base_url(self):
        try:
            from odoo.http import request
            host_url = (request.httprequest.host_url or '').rstrip('/')
            if host_url and 'localhost' not in host_url and '127.0.0.1' not in host_url:
                return host_url
        except Exception:
            pass
        return (self.env['ir.config_parameter'].sudo().get_param('web.base.url') or '').rstrip('/')

    @api.depends('banner_image')
    def _compute_banner_info(self):
        base = self._get_base_url()
        for rec in self:
            has_b = bool(rec.banner_image)
            rec.has_banner = has_b
            rec.banner_url = f"{base}/api/v1/section/{rec.id}/banner" if has_b else ''

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if rec.product_ids:
                rec.product_ids.sudo().write({'available_in_app': True})
        return records

    def write(self, vals):
        res = super().write(vals)
        if 'product_ids' in vals:
            for rec in self:
                if rec.product_ids:
                    rec.product_ids.sudo().write({'available_in_app': True})
        return res

    def get_products_data(self, partner=None, limit=20):
        """Return serialized product dictionaries formatted for the mobile app."""
        self.ensure_one()
        base = self._get_base_url()
        currency = self.env.company.currency_id
        if partner and getattr(partner, 'property_product_pricelist', None):
            currency = partner.property_product_pricelist.currency_id or currency

        products = self.env['product.product']
        if self.mode == 'recent':
            domain = [('sale_ok', '=', True), ('active', '=', True), ('available_in_app', '=', True)]
            products = self.env['product.product'].sudo().search(domain, order='create_date desc, id desc', limit=limit)
        else:
            products = self.product_ids.filtered(lambda p: p.active and p.sale_ok and getattr(p, 'available_in_app', True))[:limit]

        prices = {}
        if partner and getattr(partner, 'property_product_pricelist', None) and products:
            try:
                prices = partner.property_product_pricelist.sudo()._get_products_price(products, quantity=1)
            except Exception:
                pass

        return [{
            'id': p.id,
            'name': p.display_name,
            'code': p.default_code or '',
            'price': prices.get(p.id, p.list_price),
            'currency': currency.name,
            'image_url': f"{base}/api/v1/product/{p.id}/image",
            'has_image': bool(p.image_128),
            'cover_url': getattr(p, '_app_cover_url', lambda: '')() or f"{base}/api/v1/product/{p.id}/image",
            'has_cover': bool(getattr(p, 'cover_image_url', False) or getattr(p.product_tmpl_id, 'cover_image_url', False)),
            'category': p.categ_id.name or '',
            'category_id': p.categ_id.id,
            'pos_category_id': p.pos_categ_ids[:1].id if getattr(p, 'pos_categ_ids', None) else None,
            'pos_category_name': p.pos_categ_ids[:1].name if getattr(p, 'pos_categ_ids', None) else '',
        } for p in products]
