"""Catalogue endpoints: what the app is allowed to show and order."""
from odoo import http
from odoo.http import request

from .main import ROUTE, api_endpoint
from .firebase import current_partner


class AppProducts(http.Controller):

    def _domain(self, payload):
        domain = [
            ('sale_ok', '=', True),
            ('active', '=', True),
            ('available_in_app', '=', True),
            ('type', '!=', 'combo'),
        ]
        if payload.get('search'):
            term = payload['search'].strip()
            domain += ['|', '|',
                       ('name', 'ilike', term),
                       ('default_code', 'ilike', term),
                       ('barcode', '=', term)]
        if payload.get('category_id'):
            domain.append(('categ_id', 'child_of', int(payload['category_id'])))
        return domain

    # -------------------------------------------------------- catalogue
    @http.route('/api/v1/products', **ROUTE)
    @api_endpoint
    def products(self, partner, payload):
        limit = min(int(payload.get('limit', 30)), 100)
        offset = int(payload.get('offset', 0))

        Product = request.env['product.product'].sudo()
        domain = self._domain(payload)
        total = Product.search_count(domain)
        products = Product.search(domain, limit=limit, offset=offset,
                                  order='name asc')

        # Price the list through the customer's own pricelist, not list_price
        pricelist = partner.property_product_pricelist
        prices = {}
        if pricelist and products:
            prices = pricelist.sudo()._get_products_price(products, quantity=1)

        currency = (pricelist.currency_id if pricelist
                    else request.env.company.currency_id)

        return {
            'total': total,
            'limit': limit,
            'offset': offset,
            'products': [{
                'id': p.id,
                'name': p.display_name,
                'code': p.default_code or '',
                'category': p.categ_id.name or '',
                'category_id': p.categ_id.id,
                'price': prices.get(p.id, p.list_price),
                'currency': currency.name,
                'uom': p.uom_id.name,
                'description': p.description_sale or '',
                'image_url': f'/api/v1/product/{p.id}/image',
                'has_image': bool(p.image_128),
                'in_stock': (p.qty_available > 0) if p.is_storable else True,
            } for p in products],
        }

    # ------------------------------------------------------- categories
    @http.route('/api/v1/categories', **ROUTE)
    @api_endpoint
    def categories(self, partner, payload):
        groups = request.env['product.product'].sudo()._read_group(
            [('sale_ok', '=', True), ('active', '=', True),
             ('available_in_app', '=', True)],
            groupby=['categ_id'], aggregates=['__count'])
        return {'categories': [{
            'id': category.id,
            'name': category.display_name,
            'product_count': count,
        } for category, count in groups if category]}

    # ------------------------------------------------------------ image
    @http.route('/api/v1/product/<int:product_id>/image',
                type='http', auth='public', methods=['GET'],
                csrf=False, cors='*')
    def product_image(self, product_id, size='512', **kw):
        """Served without a token so <Image> widgets can load it directly,
        but only ever for products the app is allowed to list."""
        product = request.env['product.product'].sudo().search([
            ('id', '=', product_id),
            ('sale_ok', '=', True),
            ('active', '=', True),
            ('available_in_app', '=', True),
        ], limit=1)
        if not product:
            return request.not_found()

        field = 'image_%s' % size if size in ('128', '256', '512', '1024') \
            else 'image_512'
        stream = request.env['ir.binary']._get_image_stream_from(
            product, field_name=field)
        response = stream.get_response()
        response.headers['Cache-Control'] = 'public, max-age=86400'
        return response
