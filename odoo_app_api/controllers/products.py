"""Catalogue endpoints: what the app is allowed to show and order."""
import logging

from odoo import http, fields
from odoo.http import request

from .main import ROUTE, ROUTE_READ, api_endpoint, wallet_cards, safe_table_info
from .firebase import current_partner

_logger = logging.getLogger(__name__)


CATEGORY_ICONS = [
    (('coffee', 'espresso', 'cappuccino', 'latte', 'tea', 'cafe', 'macha', 'mocha'), 'coffee'),
    (('breakfast', 'morning', 'brunch', 'pancake', 'waffle', 'omelet', 'egg'), 'breakfast_dining'),
    (('lunch', 'midday', 'sandwich', 'wrap', 'shawarma', 'sub'), 'lunch_dining'),
    (('dinner', 'evening', 'steak', 'grill', 'bbq'), 'dinner_dining'),
    (('drink', 'beverage', 'juice', 'soda', 'water', 'smoothie', 'shake', 'cocktail', 'mocktail', 'bar', 'beer', 'wine', 'cold'), 'local_bar'),
    (('pizza', 'pasta', 'italian', 'lasagna'), 'local_pizza'),
    (('burger', 'fast food', 'fastfood', 'snack', 'fries', 'nugget', 'wings', 'hot dog', 'taco'), 'fastfood'),
    (('bakery', 'cake', 'dessert', 'sweet', 'pastry', 'cookie', 'bread', 'croissant', 'donut', 'muffin'), 'cake'),
    (('ice cream', 'icecream', 'gelato', 'frozen', 'sorbet'), 'icecream'),
    (('salad', 'vegan', 'healthy', 'vegetarian', 'fruit', 'vegetable', 'greens'), 'eco'),
    (('soup', 'ramen', 'noodle', 'stew', 'bowl'), 'ramen_dining'),
    (('seafood', 'fish', 'sushi', 'shrimp', 'salmon'), 'set_meal'),
]


def guess_category_icon(name):
    """Map category names to standard mobile/Material icon identifiers."""
    if not name:
        return 'restaurant'
    n = name.lower()
    for keywords, icon in CATEGORY_ICONS:
        if any(k in n for k in keywords):
            return icon
    return 'restaurant'


class AppProducts(http.Controller):

    BASE = [('sale_ok', '=', True), ('active', '=', True),
            ('available_in_app', '=', True)]

    def _search_term(self, payload):
        term = (payload.get('search') or '').strip()
        # A caller that forgot to fill its template variable sends the
        # placeholder itself ("[search]", "{{search}}"). Treat that as blank
        # rather than searching for a product with that literal name.
        if term.startswith(('[', '{', '<')) and term.endswith((']', '}', '>')):
            return ''
        return term

    def _is_pos_requested(self, payload):
        v = payload.get('pos_only')
        if v in (True, 1, '1', 'true', 'True'):
            return True
        if payload.get('source') == 'pos' or payload.get('type') == 'pos':
            return True
        if payload.get('pos_category_id'):
            return True
        return False

    def _domain(self, payload):
        domain = list(self.BASE) + [('type', '!=', 'combo')]
        term = self._search_term(payload)
        if term:
            domain += ['|', '|',
                       ('name', 'ilike', term),
                       ('default_code', 'ilike', term),
                       ('barcode', '=', term)]
        Product = request.env['product.product'].sudo()
        has_pos_field = 'available_in_pos' in Product._fields or 'available_in_pos' in request.env['product.template']._fields
        if has_pos_field and self._is_pos_requested(payload):
            domain.append(('available_in_pos', '=', True))

        if payload.get('pos_category_id') and 'pos_categ_ids' in Product._fields:
            domain.append(('pos_categ_ids', 'in', [int(payload['pos_category_id'])]))
        elif payload.get('category_id'):
            domain.append(('categ_id', 'child_of', int(payload['category_id'])))
        return domain

    @staticmethod
    def _in_stock(product):
        """Stock figures only exist when the Inventory app is installed.
        Without it every saleable product is orderable."""
        if 'is_storable' not in product._fields or not product.is_storable:
            return True
        return product.qty_available > 0

    def _get_base_url(self):
        try:
            host_url = (request.httprequest.host_url or '').rstrip('/')
            if host_url and 'localhost' not in host_url and '127.0.0.1' not in host_url:
                return host_url
        except Exception:
            pass
        return (request.env['ir.config_parameter'].sudo().get_param('web.base.url') or '').rstrip('/')

    # -------------------------------------------------------- catalogue
    def _get_products(self, partner, payload):
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
        extras = partner._app_product_extras(products)
        # Full address: an app's image widget cannot load a relative path.
        base = self._get_base_url()
        has_pos = 'pos_categ_ids' in Product._fields

        result = {
            'total': total,
            'limit': limit,
            'offset': offset,
            'products': [{
                'id': p.id,
                'name': p.display_name,
                'code': p.default_code or '',
                'category': p.categ_id.name or '',
                'category_id': p.categ_id.id,
                'pos_category_id': p.pos_categ_ids[:1].id if has_pos and p.pos_categ_ids else None,
                'pos_category_name': p.pos_categ_ids[:1].name if has_pos and p.pos_categ_ids else '',
                'price': prices.get(p.id, p.list_price),
                'currency': currency.name,
                'uom': p.uom_id.name,
                'description': p.description_sale or '',
                'image_url': f'{base}/api/v1/product/{p.id}/image',
                'has_image': bool(p.image_128),
                'cover_url': getattr(p, '_app_cover_url', lambda: '')() or f'{base}/api/v1/product/{p.id}/image',
                'has_cover': bool(getattr(p, 'cover_image_url', False) or getattr(p.product_tmpl_id, 'cover_image_url', False)),
                'in_stock': self._in_stock(p),
                **extras.get(p.id, {}),
            } for p in products],
        }
        if not total:
            result['hint'] = self._why_empty(payload)
        return result

    @http.route(['/api/v1/products', '/api/v1/pos/products', '/api/v1/pos_products'], **ROUTE)
    @api_endpoint
    def products(self, partner, payload):
        if '/pos/' in request.httprequest.path or '/pos_' in request.httprequest.path:
            payload = dict(payload, pos_only=True)
        return self._get_products(partner, payload)

    def _why_empty(self, payload):
        """Nothing matched. Say which condition removed everything, so the
        app developer is not left guessing between Odoo and FlutterFlow."""
        Product = request.env['product.product'].sudo()
        term = self._search_term(payload)
        counts = {
            'products_in_database': Product.search_count([('active', '=', True)]),
            'can_be_sold': Product.search_count(
                [('active', '=', True), ('sale_ok', '=', True)]),
            'and_shown_in_app': Product.search_count(self.BASE),
        }
        has_pos_field = 'available_in_pos' in Product._fields or 'available_in_pos' in request.env['product.template']._fields
        if has_pos_field and self._is_pos_requested(payload):
            counts['pos_available'] = Product.search_count(
                self.BASE + [('available_in_pos', '=', True)])

        if not counts['products_in_database']:
            counts['reason'] = 'no active products exist in Odoo'
        elif not counts['can_be_sold']:
            counts['reason'] = "no product has 'Can be Sold' ticked"
        elif not counts['and_shown_in_app']:
            counts['reason'] = "every saleable product has 'Show in Mobile App' unticked"
        elif has_pos_field and self._is_pos_requested(payload) and not counts.get('pos_available'):
            counts['reason'] = "no products have 'Point of Sale' (available_in_pos) ticked"
        elif payload.get('pos_category_id'):
            counts['reason'] = 'no product in that POS category'
        elif payload.get('category_id'):
            counts['reason'] = 'no product in that category'
        elif term:
            counts['reason'] = f'nothing matches the search term {term!r}'
        else:
            counts['reason'] = 'the offset is past the end of the list'
        return counts

    # ------------------------------------------------------- categories
    def _get_categories(self, partner, payload):
        base = self._get_base_url()
        if payload.get('type') == 'pos' or payload.get('source') == 'pos':
            return self._get_pos_categories(partner, payload)

        Product = request.env['product.product'].sudo()
        groups = Product._read_group(
            self.BASE, groupby=['categ_id'], aggregates=['__count'])
        cats = [{
            'id': category.id,
            'name': category.display_name,
            'icon': getattr(category, 'app_icon', None) or guess_category_icon(category.name),
            'image_url': f'{base}/api/v1/category/{category.id}/image',
            'has_image': bool(getattr(category, 'image_128', False)),
            'product_count': count,
        } for category, count in groups if category]
        return {'total': len(cats), 'categories': cats}

    @http.route('/api/v1/categories', **ROUTE_READ)
    @api_endpoint
    def categories(self, partner, payload):
        return self._get_categories(partner, payload)

    def _get_pos_categories(self, partner, payload):
        """List POS product categories with icons, images, and product counts."""
        base = self._get_base_url()
        if 'pos.category' not in request.env:
            return {'total': 0, 'categories': []}

        PosCategory = request.env['pos.category'].sudo()
        domain = [('active', '=', True)] if 'active' in PosCategory._fields else []
        if 'available_in_app' in PosCategory._fields and not payload.get('include_all'):
            domain.append(('available_in_app', '=', True))
        categories = PosCategory.search(domain, order='sequence asc, name asc')

        Product = request.env['product.product'].sudo()
        has_pos_field = 'available_in_pos' in Product._fields or 'available_in_pos' in request.env['product.template']._fields
        pos_filter = [('available_in_pos', '=', True)] if has_pos_field else []
        counts = {}
        if 'pos_categ_ids' in Product._fields:
            for cat in categories:
                counts[cat.id] = Product.search_count(
                    self.BASE + pos_filter + [('pos_categ_ids', 'in', [cat.id])]
                )

        cats = [{
            'id': cat.id,
            'name': cat.name,
            'icon': getattr(cat, 'app_icon', None) or guess_category_icon(cat.name),
            'image_url': f'{base}/api/v1/pos/category/{cat.id}/image',
            'has_image': bool(cat.image_128),
            'available_in_app': getattr(cat, 'available_in_app', True),
            'sequence': getattr(cat, 'sequence', 0),
            'parent_id': cat.parent_id.id if cat.parent_id else None,
            'product_count': counts.get(cat.id, 0),
        } for cat in categories]
        return {'total': len(cats), 'categories': cats}

    @http.route([
        '/api/v1/pos/categories',
        '/api/v1/pos_categories',
        '/api/v1/pos-categories',
        '/api/v1/menu/categories',
    ], **ROUTE_READ)
    @api_endpoint
    def pos_categories(self, partner, payload):
        """List POS product categories with icons, images, and product counts."""
        return self._get_pos_categories(partner, payload)

    # --------------------------------------------------- curated sections
    def _get_sections_data(self, partner, payload=None):
        if 'app.section' not in request.env:
            return []
        payload = payload or {}
        now = fields.Datetime.now()
        domain = [
            ('active', '=', True),
            '|', ('date_start', '=', False), ('date_start', '<=', now),
            '|', ('date_end', '=', False), ('date_end', '>=', now),
        ]
        if payload.get('code'):
            domain.append(('code', '=', payload['code']))
        Section = request.env['app.section'].sudo()
        sections = Section.search(domain, order='sequence asc, id asc')

        item_limit = min(int(payload.get('section_product_limit') or 15), 50)
        result = []
        for sec in sections:
            prods = sec.get_products_data(partner=partner, limit=item_limit)
            result.append({
                'id': sec.id,
                'code': sec.code,
                'title': sec.name,
                'name': sec.name,
                'subtitle': sec.subtitle or '',
                'badge': sec.badge_text or '',
                'sequence': sec.sequence,
                'mode': sec.mode,
                'has_banner': sec.has_banner,
                'banner_url': sec.banner_url or '',
                'product_count': len(prods),
                'products': prods,
            })
        return result

    @http.route([
        '/api/v1/sections',
        '/api/v1/app/sections',
        '/api/v1/promotions',
    ], **ROUTE_READ)
    @api_endpoint
    def sections(self, partner, payload):
        """Returns active curated app sections with their products."""
        data = self._get_sections_data(partner, payload)
        return {
            'total': len(data),
            'sections': data,
        }

    # --------------------------------------------------- unified menu / init
    @http.route(['/api/v1/menu', '/api/v1/app/init'], **ROUTE)
    @api_endpoint
    def menu(self, partner, payload):
        """Unified bootstrap endpoint: returns customer profile, wallet balance,
        allowance limits & status, active POS session & tables, categories, sections, and products.
        """
        base = self._get_base_url()
        company = partner.company_id or request.env.company
        currency = (partner.property_product_pricelist.currency_id
                    if partner.property_product_pricelist
                    else company.currency_id)
        cards = wallet_cards(partner)
        balance = sum(cards.mapped('points'))

        # Customer & Allowance
        allowance_data = {'has_allowance': False, 'status': 'none', 'summary': '', 'limits': []}
        try:
            allowance_data = partner._app_allowance_extras() or allowance_data
        except Exception:
            _logger.exception("Error evaluating allowance extras for partner %s", partner.id)

        me_extras = {}
        try:
            me_extras = partner._app_me_extras() or {}
        except Exception:
            _logger.exception("Error evaluating me extras for partner %s", partner.id)

        customer = {
            'partner_id': partner.id,
            'name': partner.name,
            'barcode': partner.barcode or '',
            'barcode_image_url': (
                f"{base}/report/barcode/Code128/{partner.barcode}"
                "?width=600&height=150&humanreadable=1" if partner.barcode else ''),
            'wallet_balance': balance,
            'currency': currency.name,
            'is_staff': me_extras.get('is_staff', False),
            'has_allowance': allowance_data.get('has_allowance', False),
            'allowance': allowance_data,
        }

        # POS Open Session & Dining Tables
        pos_data = {
            'is_open': False,
            'session_id': None,
            'session_name': '',
            'pos_id': None,
            'pos_name': '',
            'tables': [],
        }
        try:
            if 'pos.session' in request.env:
                PosSession = request.env['pos.session'].sudo()
                # Prioritize POS 7 ("From App") if open, otherwise most recent opened session
                session = PosSession.search([('state', '=', 'opened'), ('config_id', '=', 7)], limit=1, order='id desc')
                if not session:
                    session = PosSession.search([('state', '=', 'opened')], limit=1, order='id desc')
                if session:
                    pos_data['is_open'] = True
                    pos_data['session_id'] = session.id
                    pos_data['session_name'] = session.name
                    pos_data['pos_id'] = session.config_id.id
                    pos_data['pos_name'] = session.config_id.name

                    has_restaurant = 'restaurant.floor' in request.env and 'restaurant.table' in request.env
                    if has_restaurant and hasattr(session.config_id, 'floor_ids') and session.config_id.floor_ids:
                        for floor in session.config_id.floor_ids:
                            for t in floor.table_ids.filtered(lambda tbl: getattr(tbl, 'active', True)):
                                tbl_info = safe_table_info(t)
                                pos_data['tables'].append({
                                    'table_id': t.id,
                                    'table_number': tbl_info['table_number'],
                                    'table_name': tbl_info['table_name'],
                                    'seats': getattr(t, 'seats', 1),
                                    'floor_name': floor.name,
                                    'floor_id': floor.id,
                                })
                    elif has_restaurant and 'restaurant.table' in request.env:
                        Table = request.env['restaurant.table'].sudo()
                        for t in Table.search([('active', '=', True)], limit=20):
                            tbl_info = safe_table_info(t)
                            pos_data['tables'].append({
                                'table_id': t.id,
                                'table_number': tbl_info['table_number'],
                                'table_name': tbl_info['table_name'],
                                'seats': getattr(t, 'seats', 1),
                                'floor_name': t.floor_id.name if t.floor_id else '',
                            })
        except Exception:
            _logger.exception("Error loading POS session/tables in menu")

        # Categories
        cat_result = self._get_pos_categories(partner, payload)
        categories = cat_result.get('categories', [])
        if not categories:
            cat_result = self._get_categories(partner, payload)
            categories = cat_result.get('categories', [])

        # Curated Sections (Today's Best, Featured, Special Offers, etc.)
        sections = self._get_sections_data(partner, payload)

        # Products (default to 10 items so the unified bootstrap payload fits comfortably
        # within FlutterFlow's 50,000-character test preview buffer; apps can pass ?limit=50 as needed)
        limit = min(int(payload.get('limit') or 10), 100)
        prod_payload = dict(payload, limit=limit, pos_only=True)
        prod_result = self._get_products(partner, prod_payload)
        products = prod_result.get('products', [])

        return {
            'customer': customer,
            'pos': pos_data,
            'categories': categories,
            'sections': sections,
            'products': products,
            'total_products': prod_result.get('total', len(products)),
        }

    # ------------------------------------------------------------ images
    @http.route('/api/v1/product/<int:product_id>/image',
                type='http', auth='public', methods=['GET'],
                csrf=False, cors='*')
    def product_image(self, product_id, size='512', **kw):
        """Served without a token so <Image> widgets can load it directly,
        but only ever for products the app is allowed to list."""
        Product = request.env['product.product'].sudo()
        product = Product.browse(product_id).exists()
        if not product or not product.active or not product.sale_ok:
            return request.not_found()

        field = 'image_%s' % size if size in ('128', '256', '512', '1024') \
            else 'image_512'
        target = product
        if not getattr(product, field, None) and product.product_tmpl_id and getattr(product.product_tmpl_id, field, None):
            target = product.product_tmpl_id

        stream = request.env['ir.binary']._get_image_stream_from(
            target, field_name=field)
        response = stream.get_response()
        response.headers['Cache-Control'] = 'public, max-age=86400'
        return response

    @http.route('/api/v1/pos/category/<int:category_id>/image',
                type='http', auth='public', methods=['GET'],
                csrf=False, cors='*')
    def pos_category_image(self, category_id, **kw):
        """Served without a token so <Image> widgets can load POS category images directly."""
        if 'pos.category' not in request.env:
            return request.not_found()
        cat = request.env['pos.category'].sudo().browse(category_id).exists()
        if not cat or not getattr(cat, 'image_128', False):
            return request.not_found()
        if 'active' in cat._fields and not cat.active:
            return request.not_found()
        stream = request.env['ir.binary']._get_image_stream_from(
            cat, field_name='image_128')
        response = stream.get_response()
        response.headers['Cache-Control'] = 'public, max-age=86400'
        return response

    @http.route('/api/v1/category/<int:category_id>/image',
                type='http', auth='public', methods=['GET'],
                csrf=False, cors='*')
    def category_image(self, category_id, **kw):
        """Served without a token for product category image if available."""
        cat = request.env['product.category'].sudo().browse(category_id).exists()
        if not cat or not getattr(cat, 'image_128', False):
            return request.not_found()
        if 'active' in cat._fields and not cat.active:
            return request.not_found()
        stream = request.env['ir.binary']._get_image_stream_from(
            cat, field_name='image_128')
        response = stream.get_response()
        response.headers['Cache-Control'] = 'public, max-age=86400'
        return response

    @http.route('/api/v1/section/<int:section_id>/banner',
                type='http', auth='public', methods=['GET'],
                csrf=False, cors='*')
    def section_banner(self, section_id, **kw):
        """Served without a token so <Image> widgets can load section promo banners directly."""
        if 'app.section' not in request.env:
            return request.not_found()
        section = request.env['app.section'].sudo().browse(section_id).exists()
        if not section or not section.banner_image:
            return request.not_found()
        if not section.active:
            return request.not_found()
        stream = request.env['ir.binary']._get_image_stream_from(
            section, field_name='banner_image')
        response = stream.get_response()
        response.headers['Cache-Control'] = 'public, max-age=86400'
        return response

