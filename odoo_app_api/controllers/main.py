import functools
import json
import logging
import math

from psycopg2 import OperationalError
from psycopg2.errors import LockNotAvailable
from werkzeug.exceptions import HTTPException

from odoo import fields, http
from odoo.exceptions import AccessError, ConcurrencyError, UserError
from odoo.http import request
from odoo.tools import SQL

from ..api_error import ApiError
from .firebase import current_partner

_logger = logging.getLogger(__name__)

ROUTE = dict(type='http', auth='public', methods=['POST'], csrf=False, cors='*')
ROUTE_READ = dict(type='http', auth='public', methods=['GET', 'POST'], csrf=False, cors='*')


def _rollback():
    """Discard everything a failed call wrote.

    Odoo commits whatever a controller wrote once it returns a response, and
    `api_endpoint` turns exceptions into responses - so without this, a
    wallet debited just before a failing payment registration would be saved.
    """
    env = request.env
    env.cr.rollback()
    env.transaction.reset()
    env.registry.reset_changes()


def api_endpoint(func):
    """Resolve the Firebase user, hand it to the endpoint, serialise errors."""
    @functools.wraps(func)
    def wrapper(self, **kw):
        try:
            partner = current_partner()
            payload = {}
            if request.httprequest.data:
                try:
                    payload = request.get_json_data() or {}
                except Exception:
                    payload = {}
            if not payload and request.httprequest.args:
                payload = dict(request.httprequest.args)
            return request.make_json_response(func(self, partner, payload, **kw))
        except (OperationalError, ConcurrencyError):
            # Serialization failure: Odoo rolls back and retries the request.
            raise
        except ApiError as err:
            _rollback()
            return request.make_json_response({'error': err.code, **err.details})
        except HTTPException as err:
            _rollback()
            return request.make_json_response(
                {'error': err.description}, status=err.code)
        except (UserError, AccessError) as err:
            _rollback()
            return request.make_json_response(
                {'error': err.args[0] if err.args else 'forbidden'}, status=400)
        except (KeyError, TypeError, ValueError) as err:
            _rollback()
            _logger.info("Bad request to %s: %s", func.__name__, err, exc_info=True)
            return request.make_json_response({'error': 'bad_request', 'message': str(err)}, status=400)
        except Exception as err:                             # noqa: BLE001
            _rollback()
            _logger.exception("App API error in %s: %s", func.__name__, err)
            return request.make_json_response({'error': 'server_error', 'message': str(err)}, status=400)
    return wrapper




def lock_for_payment(records):
    """Row-lock `records` until the request ends; False if another request
    already holds them.

    Taken before calling the gateway, so a double tap gets
    `payment_in_progress` instead of charging the customer twice. If the rows
    changed since this request started, PostgreSQL raises a serialization
    error and Odoo retries the request - still before any money has moved.
    """
    try:
        with request.env.cr.savepoint(flush=False):
            request.env.cr.execute(SQL(
                "SELECT id FROM %s WHERE id IN %s FOR NO KEY UPDATE NOWAIT",
                SQL.identifier(records._table), tuple(records.ids)))
    except LockNotAvailable:
        return False
    return True


def owned_order(partner, order_id):
    """Never browse an id straight from the app - scope it to the caller."""
    return request.env['sale.order'].sudo().search([
        ('id', '=', int(order_id or 0)),
        ('partner_id', 'child_of', partner.commercial_partner_id.id),
    ], limit=1)


def wallet_cards(partner):
    """The caller's eWallet cards that can still be spent."""
    return request.env['loyalty.card'].sudo().search([
        ('program_type', '=', 'ewallet'),
        ('partner_id', '=', partner.commercial_partner_id.id),
        '|', ('expiration_date', '=', False),
             ('expiration_date', '>=', fields.Date.today()),
    ])


def safe_table_info(table):
    """Safely extract table number and display name for Odoo 19 restaurant.table,
    which has NO 'name' field in standard Odoo 19 and where display_name can fail if _rec_name='name'."""
    if not table:
        return {'table_id': None, 'table_number': '', 'table_name': 'Dine-In'}
    tid = table.id
    tnum = None
    if 'table_number' in table._fields:
        try:
            val = table.table_number
            if val is not None and val != '':
                tnum = str(val)
        except Exception:
            pass
    if not tnum:
        tnum = str(tid)

    tname = None
    if 'table_name' in table._fields:
        try:
            val = table.table_name
            if val:
                tname = str(val).strip()
        except Exception:
            pass
    if not tname and 'name' in table._fields:
        try:
            val = table.name
            if val:
                tname = str(val).strip()
        except Exception:
            pass
    if not tname:
        tname = f"Table {tnum}"

    return {
        'table_id': tid,
        'table_number': tnum,
        'table_name': tname,
    }


class AppApi(http.Controller):

    # ---------------------------------------------------------------- me
    @http.route('/api/v1/me', **ROUTE)
    @api_endpoint
    def me(self, partner, payload):
        """First call after Firebase sign-in. Creates/links the contact."""
        base = (request.env['ir.config_parameter'].sudo()
                .get_param('web.base.url') or '').rstrip('/')
        code = partner.barcode or ''
        data = {
            'partner_id': partner.id,
            'name': partner.name,
            'email': partner.email or '',
            'phone': partner.phone or '',
            'street': partner.street or '',
            'city': partner.city or '',
            'country': partner.country_id.name or '',
            'currency': partner.company_id.currency_id.name
                        or request.env.company.currency_id.name,
            # Membership code. Render it in the app with a barcode widget, or
            # just load one of these images - both routes are public and
            # render whatever value you hand them.
            'barcode': code,
            'barcode_image_url': (
                f"{base}/report/barcode/Code128/{code}"
                "?width=600&height=150&humanreadable=1" if code else ''),
            'qr_image_url': (
                f"{base}/report/barcode/QR/{code}?width=400&height=400"
                if code else ''),
            'avatar_url': f"{base}/web/image/res.partner/{partner.id}/avatar_128",
        }
        data.update(partner._app_me_extras())
        return data

    @http.route('/api/v1/me/update', **ROUTE)
    @api_endpoint
    def me_update(self, partner, payload):
        allowed = {'name', 'phone', 'street', 'street2', 'city', 'zip'}
        vals = {k: v for k, v in payload.items() if k in allowed}
        if vals:
            partner.sudo().write(vals)
        return {'updated': True}

    # ------------------------------------------------------------ wallet
    @http.route('/api/v1/wallet', **ROUTE)
    @api_endpoint
    def wallet(self, partner, payload):
        cards = wallet_cards(partner)
        points = sum(cards.mapped('points'))
        lines = []
        if cards:
            History = request.env['loyalty.history'].sudo()
            order_field = 'create_date desc' if 'create_date' in History._fields else 'id desc'
            history = History.search([('card_id', 'in', cards.ids)], order=order_field, limit=20)
            lines = [{
                'description': h.description or '',
                'points': getattr(h, 'used', None) if getattr(h, 'used', None) is not None else getattr(h, 'points', 0),
                'date': (getattr(h, 'create_date', None) or getattr(h, 'date', None) or '').isoformat() if (getattr(h, 'create_date', None) or getattr(h, 'date', None)) else '',
            } for h in history]
        return {
            'balance': points,
            'currency': (partner.company_id.currency_id.name
                         or request.env.company.currency_id.name),
            'has_wallet': bool(cards),
            'history': lines,
        }

    # ------------------------------------------------------------ orders & customer search
    @http.route(['/api/v1/orders', '/api/v1/orders/search'], **ROUTE)
    @api_endpoint
    def orders(self, partner, payload):
        """Search and list orders with optional filtering by order number, status, or customer."""
        limit = min(int(payload.get('limit', 20)), 100)
        offset = int(payload.get('offset', 0))
        partner_id = partner.commercial_partner_id.id
        filter_type = payload.get('order_type')  # optional: "sale" | "pos"
        search_term = (payload.get('search') or payload.get('query') or payload.get('order_number') or '').strip()
        status_filter = (payload.get('status') or '').lower().strip()
        unpaid_only = payload.get('unpaid_only') in (True, 'true', 'True', 1, '1') or status_filter in ('unpaid', 'draft', 'open')
        all_customers = payload.get('all_customers') in (True, 'true', 'True', 1, '1') or bool(search_term)

        all_orders = []
        total = 0

        SaleOrder = request.env['sale.order'].sudo()
        PosOrder = request.env['pos.order'].sudo() if 'pos.order' in request.env else None

        # Build Sale Order domain
        sale_domain = []
        if not all_customers:
            sale_domain.append(('partner_id', 'child_of', partner_id))
        if unpaid_only:
            sale_domain.append(('state', 'in', ('draft', 'sent', 'sale')))
        if search_term:
            s_parts = ['|', ('name', 'ilike', search_term), ('partner_id.name', 'ilike', search_term)]
            if search_term.isdigit():
                s_parts = ['|', ('id', '=', int(search_term))] + s_parts
            sale_domain.extend(s_parts)

        # Build POS Order domain
        pos_domain = []
        if PosOrder:
            if not all_customers:
                pos_domain.append(('partner_id', 'child_of', partner_id))
            if unpaid_only:
                pos_domain.append(('state', 'in', ('draft',)))
            if search_term:
                p_parts = [
                    '|', '|', '|',
                    ('pos_reference', 'ilike', search_term),
                    ('name', 'ilike', search_term),
                    ('partner_id.name', 'ilike', search_term),
                    ('partner_id.phone', 'ilike', search_term)
                ]
                if search_term.isdigit():
                    p_parts = ['|', ('id', '=', int(search_term))] + p_parts
                pos_domain.extend(p_parts)

        if filter_type != 'pos':
            sale_orders = SaleOrder.search(sale_domain, order='date_order desc, id desc', limit=limit + offset)
            all_orders.extend([self._order_dict(o) for o in sale_orders])
            total += SaleOrder.search_count(sale_domain)

        if filter_type != 'sale' and PosOrder:
            pos_orders = PosOrder.search(pos_domain, order='date_order desc, id desc', limit=limit + offset)
            all_orders.extend([self._pos_order_dict(po) for po in pos_orders])
            total += PosOrder.search_count(pos_domain)

        # Sort combined orders newest first
        all_orders.sort(key=lambda x: x.get('date') or '', reverse=True)
        paged_orders = all_orders[offset:offset + limit]

        return {
            'total': total,
            'limit': limit,
            'offset': offset,
            'orders': paged_orders,
        }

    @http.route('/api/v1/orders/detail', **ROUTE)
    @api_endpoint
    def order_detail(self, partner, payload):
        """Body: {"order_id": 123 or "260-7-000016", "order_type": "sale"|"pos"}"""
        ref_or_id = (payload.get('order_id')
                     or payload.get('order_number')
                     or payload.get('pos_reference')
                     or payload.get('name'))
        if not ref_or_id:
            raise ApiError('no_order_specified', message='Please provide an order ID or order number.')

        order_type = payload.get('order_type')
        partner_id = partner.commercial_partner_id.id
        all_customers = payload.get('all_customers') in (True, 'true', 'True', 1, '1')

        # Check POS Order first
        if order_type != 'sale' and 'pos.order' in request.env:
            PosOrder = request.env['pos.order'].sudo()
            pos_domain = []
            if str(ref_or_id).isdigit():
                pos_domain = ['|', ('id', '=', int(ref_or_id)), ('pos_reference', 'ilike', str(ref_or_id))]
            else:
                pos_domain = ['|', ('pos_reference', '=', str(ref_or_id)), ('name', '=', str(ref_or_id))]

            if not all_customers:
                owned_po = PosOrder.search(pos_domain + [('partner_id', 'child_of', partner_id)], limit=1)
                if owned_po:
                    return self._pos_order_dict(owned_po)

            po = PosOrder.search(pos_domain, limit=1)
            if po:
                return self._pos_order_dict(po)

        # Check Sale Order
        SaleOrder = request.env['sale.order'].sudo()
        sale_domain = []
        if str(ref_or_id).isdigit():
            sale_domain = ['|', ('id', '=', int(ref_or_id)), ('name', 'ilike', str(ref_or_id))]
        else:
            sale_domain = [('name', '=', str(ref_or_id))]

        if not all_customers:
            owned_so = SaleOrder.search(sale_domain + [('partner_id', 'child_of', partner_id)], limit=1)
            if owned_so:
                return self._order_dict(owned_so)

        so = SaleOrder.search(sale_domain, limit=1)
        if so:
            return self._order_dict(so)

        raise ApiError('order_not_found')

    @http.route(['/api/v1/customers/lookup', '/api/v1/customer/lookup', '/api/v1/customers/search'], **ROUTE)
    @api_endpoint
    def customer_lookup(self, partner, payload):
        """Lookup customer by barcode, phone, name, email, or ID to assign to an order or check wallet/credit."""
        query = (payload.get('query') or payload.get('search') or payload.get('barcode')
                 or payload.get('phone') or str(payload.get('partner_id') or '')).strip()
        Partner = request.env['res.partner'].sudo()

        domain = [('active', '=', True)]
        if query:
            if query.isdigit() and len(query) <= 6:
                domain.extend(['|', ('id', '=', int(query)), ('phone', 'ilike', query)])
            else:
                domain.extend([
                    '|', '|', '|',
                    ('barcode', '=', query),
                    ('phone', 'ilike', query),
                    ('name', 'ilike', query),
                    ('email', 'ilike', query),
                ])
        else:
            domain.append(('id', '=', partner.id))

        matches = Partner.search(domain, limit=10)
        base = self._get_base_url()

        result = []
        for p in matches:
            commercial = p.commercial_partner_id
            cards = wallet_cards(p)
            balance = sum(cards.mapped('points'))
            company = p.company_id or request.env.company
            credit_limit = commercial.credit_limit if company.account_use_credit_limit else 0.0
            credit_owed = commercial.credit
            credit_available = max(credit_limit - credit_owed, 0.0) if credit_limit else None

            allowance_data = {'has_allowance': False, 'status': 'none', 'summary': ''}
            if hasattr(p, '_app_allowance_extras'):
                try:
                    allowance_data = p._app_allowance_extras() or allowance_data
                except Exception:
                    pass

            result.append({
                'id': p.id,
                'name': p.name,
                'barcode': p.barcode or '',
                'barcode_image_url': (
                    f"{base}/report/barcode/Code128/{p.barcode}"
                    "?width=600&height=150&humanreadable=1" if p.barcode else ''),
                'phone': p.phone or '',
                'email': p.email or '',
                'wallet_balance': balance,
                'has_wallet': balance > 0,
                'credit_owed': round(credit_owed, 2),
                'credit_limit': credit_limit or None,
                'credit_available': round(credit_available, 2) if credit_available is not None else None,
                'allowance': allowance_data,
            })

        return {
            'total': len(result),
            'customers': result,
            'customer': result[0] if result else None,
        }


    @http.route('/api/v1/orders/create', **ROUTE)
    @api_endpoint
    def order_create(self, partner, payload):
        """A quotation only. /api/v1/checkout places and pays in one call."""
        order = self._create_app_order(partner, payload)
        return self._order_dict(order)

    def _create_app_order(self, partner, payload):
        """Validate the cart and create the quotation, or raise ApiError."""
        lines = payload.get('lines')
        if not lines and (payload.get('pid') or payload.get('product_id')):
            pid = payload.get('pid') or payload.get('product_id')
            qty = payload.get('qty') or 1
            lines = [{'product_id': pid, 'qty': qty}]
        lines = lines or []
        if isinstance(lines, str):
            # FlutterFlow can send a JSON variable as text: accept both.
            try:
                lines = json.loads(lines)
            except ValueError:
                raise ApiError('bad_lines')
        if not lines:
            raise ApiError('no_lines')
        try:
            wanted = [(int(line.get('product_id') or line.get('productId')), float(line.get('qty', 1)))
                      for line in lines]
        except (AttributeError, KeyError, TypeError, ValueError):
            raise ApiError('bad_lines')
        if any(not (math.isfinite(qty) and qty > 0) for _pid, qty in wanted):
            raise ApiError('bad_qty')

        # The same product may sit on two lines; every id must still exist.
        product_ids = list({product_id for product_id, _qty in wanted})
        products = request.env['product.product'].sudo().browse(
            product_ids).exists()
        if len(products) != len(product_ids):
            raise ApiError('unknown_product')
        # Only let the app order things it is allowed to see
        if any(not p.sale_ok or not p.active or not p.available_in_app
               for p in products):
            raise ApiError('product_not_orderable')
        # Check stock availability for storable goods
        out_of_stock = [
            p.display_name for p in products
            if getattr(p, 'is_storable', False) and p.qty_available <= 0
        ]
        if out_of_stock:
            raise ApiError('out_of_stock', products=out_of_stock)

        order = request.env['sale.order'].sudo().create({
            'partner_id': partner.id,
            'is_app_order': True,
            'origin': 'Mobile app',
            'client_order_ref': payload.get('client_ref') or False,
            'note': payload.get('note') or False,
            'order_line': [(0, 0, {
                'product_id': product_id,
                'product_uom_qty': qty,
            }) for product_id, qty in wanted],
        })
        order.message_post(body="Order placed from the mobile app.")
        return order

    def _get_base_url(self):
        try:
            host_url = (request.httprequest.host_url or '').rstrip('/')
            if host_url and 'localhost' not in host_url and '127.0.0.1' not in host_url:
                return host_url
        except Exception:
            pass
        return (request.env['ir.config_parameter'].sudo().get_param('web.base.url') or '').rstrip('/')

    def _order_dict(self, order):
        base = self._get_base_url()
        invoices = order.invoice_ids.filtered(
            lambda m: m.state == 'posted' and m.move_type == 'out_invoice')
        due = sum(invoices.mapped('amount_residual'))
        return {
            'id': order.id,
            'name': order.name,
            'order_type': 'sale',
            'partner_id': order.partner_id.id if order.partner_id else None,
            'partner_name': order.partner_id.name if order.partner_id else '',
            'date': order.date_order.isoformat() if order.date_order else '',
            'state': order.state,
            'state_label': dict(
                order._fields['state']._description_selection(order.env)
            ).get(order.state, order.state) if 'state' in order._fields else order.state,
            'amount_total': order.amount_total,
            'currency': order.currency_id.name,
            'payment_method': order.app_payment_method or '',
            'payment_status': self._payment_status(order, invoices, due),
            'amount_due': round(due, 2),
            'invoice_ids': invoices.ids,
            'lines': [{
                'product_id': line.product_id.id,
                'name': line.product_id.name or line.product_id.display_name,
                'product': line.product_id.display_name,
                'qty': line.product_uom_qty,
                'price_unit': line.price_unit,
                'subtotal': line.price_subtotal,
                'image_url': f"{base}/api/v1/product/{line.product_id.id}/image",
                'has_image': bool(line.product_id.image_128),
                'cover_url': getattr(line.product_id, '_app_cover_url', lambda: '')() or f"{base}/api/v1/product/{line.product_id.id}/image",
                'has_cover': bool(getattr(line.product_id, 'cover_image_url', False) or getattr(line.product_id.product_tmpl_id, 'cover_image_url', False)),
            } for line in order.order_line if not line.display_type],
        }

    def _pos_order_dict(self, order):
        base = self._get_base_url()
        table_num = ''
        table_name = 'Dine-In'
        if 'table_id' in order._fields and order.table_id:
            tbl_info = safe_table_info(order.table_id)
            table_num = tbl_info['table_number']
            table_name = tbl_info['table_name']

        pm_name = getattr(order, 'app_payment_method', None) or 'wallet'
        if order.payment_ids:
            pm = order.payment_ids[0].payment_method_id
            pm_name = pm.name or pm_name

        ref = getattr(order, 'pos_reference', False) or order.name or f"Order #{order.id}"
        display_name = order.name or ''
        if display_name.strip() in ('/', ''):
            display_name = ref
        elif display_name.strip() == '/ REFUND':
            display_name = f"{ref} (Refund)"

        state_label = dict(
            order._fields['state']._description_selection(order.env)
        ).get(order.state, order.state) if 'state' in order._fields else order.state

        return {
            'id': order.id,
            'name': display_name,
            'pos_reference': ref,
            'order_type': 'pos',
            'partner_id': order.partner_id.id if order.partner_id else None,
            'partner_name': order.partner_id.name if order.partner_id else '',
            'date': order.date_order.isoformat() if order.date_order else '',
            'state': order.state,
            'state_label': state_label,
            'amount_total': order.amount_total,
            'currency': order.currency_id.name if order.currency_id else '',
            'payment_method': getattr(order, 'app_payment_method', None) or 'wallet',
            'payment_method_name': pm_name,
            'payment_status': 'paid' if order.state in ('paid', 'done') else order.state,
            'amount_due': 0.0 if order.state in ('paid', 'done') else order.amount_total,
            'table_no': table_num,
            'table_name': table_name,
            'invoice_ids': [order.account_move.id] if getattr(order, 'account_move', None) else [],
            'lines': [{
                'product_id': line.product_id.id,
                'name': line.product_id.name or line.product_id.display_name,
                'product': line.product_id.display_name,
                'qty': line.qty,
                'price_unit': line.price_unit,
                'subtotal': line.price_subtotal,
                'image_url': f"{base}/api/v1/product/{line.product_id.id}/image",
                'has_image': bool(line.product_id.image_128),
                'cover_url': getattr(line.product_id, '_app_cover_url', lambda: '')() or f"{base}/api/v1/product/{line.product_id.id}/image",
                'has_cover': bool(getattr(line.product_id, 'cover_image_url', False) or getattr(line.product_id.product_tmpl_id, 'cover_image_url', False)),
            } for line in order.lines],
        }

    @staticmethod
    def _payment_status(order, invoices, due):
        """One word for the order history page."""
        if order.state == 'cancel':
            return 'cancelled'
        if order.state in ('draft', 'sent'):
            return 'quotation'
        if not invoices:
            return 'paid' if order.app_payment_reference else 'not_invoiced'
        if order.currency_id.is_zero(due):
            return 'paid'
        if order.currency_id.compare_amounts(due, sum(invoices.mapped('amount_total'))) < 0:
            return 'partly_paid'
        return 'to_pay'
