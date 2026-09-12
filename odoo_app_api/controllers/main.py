import functools
import logging
import math

from psycopg2 import OperationalError
from psycopg2.errors import LockNotAvailable
from werkzeug.exceptions import HTTPException

from odoo import fields, http
from odoo.exceptions import AccessError, ConcurrencyError, UserError
from odoo.http import request
from odoo.tools import SQL

from .firebase import current_partner

_logger = logging.getLogger(__name__)

ROUTE = dict(type='http', auth='public', methods=['POST'], csrf=False, cors='*')


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
            payload = request.get_json_data() if request.httprequest.data else {}
            return request.make_json_response(func(self, partner, payload, **kw))
        except (OperationalError, ConcurrencyError):
            # Serialization failure: Odoo rolls back and retries the request.
            raise
        except HTTPException as err:
            _rollback()
            return request.make_json_response(
                {'error': err.description}, status=err.code)
        except (UserError, AccessError) as err:
            _rollback()
            return request.make_json_response(
                {'error': err.args[0] if err.args else 'forbidden'}, status=400)
        except (KeyError, TypeError, ValueError):
            _rollback()
            _logger.info("Bad request to %s", func.__name__, exc_info=True)
            return request.make_json_response({'error': 'bad_request'}, status=400)
        except Exception:                             # noqa: BLE001
            _rollback()
            _logger.exception("App API error in %s", func.__name__)
            # The details are in the server log, not in the app.
            return request.make_json_response({'error': 'server_error'}, status=400)
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


class AppApi(http.Controller):

    # ---------------------------------------------------------------- me
    @http.route('/api/v1/me', **ROUTE)
    @api_endpoint
    def me(self, partner, payload):
        """First call after Firebase sign-in. Creates/links the contact."""
        base = (request.env['ir.config_parameter'].sudo()
                .get_param('web.base.url') or '').rstrip('/')
        code = partner.barcode or ''
        return {
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
        }

    @http.route('/api/v1/me/update', **ROUTE)
    @api_endpoint
    def me_update(self, partner, payload):
        allowed = {'name', 'phone', 'street', 'street2', 'city', 'zip'}
        vals = {k: v for k, v in payload.items() if k in allowed}
        if vals:
            partner.sudo().write(vals)
        return {'ok': True}

    # ------------------------------------------------------------ wallet
    @http.route('/api/v1/wallet', **ROUTE)
    @api_endpoint
    def wallet(self, partner, payload):
        cards = request.env['loyalty.card'].sudo().search([
            ('program_type', '=', 'ewallet'),
            ('partner_id', '=', partner.commercial_partner_id.id),
            '|', ('expiration_date', '=', False),
                 ('expiration_date', '>=', fields.Date.today()),
        ])
        history = cards.history_ids.sorted('create_date', reverse=True)[:50]
        return {
            'balance': sum(cards.mapped('points')),
            'currency': partner.company_id.currency_id.name
                        or request.env.company.currency_id.name,
            'transactions': [{
                'id': h.id,
                'date': h.create_date.isoformat(),
                'description': h.description or '',
                'credit': h.issued,
                'debit': h.used,
            } for h in history],
        }

    # ------------------------------------------------------------ orders
    @http.route('/api/v1/orders', **ROUTE)
    @api_endpoint
    def orders(self, partner, payload):
        limit = min(int(payload.get('limit', 20)), 100)
        offset = int(payload.get('offset', 0))
        sale_orders = request.env['sale.order'].sudo().search(
            [('partner_id', 'child_of', partner.commercial_partner_id.id)],
            order='date_order desc', limit=limit, offset=offset)
        return {'orders': [self._order_dict(o) for o in sale_orders]}

    @http.route('/api/v1/orders/create', **ROUTE)
    @api_endpoint
    def order_create(self, partner, payload):
        lines = payload.get('lines') or []
        if not lines:
            return {'error': 'no_lines'}
        try:
            wanted = [(int(line['product_id']), float(line.get('qty', 1)))
                      for line in lines]
        except (AttributeError, KeyError, TypeError, ValueError):
            return {'error': 'bad_lines'}
        if any(not (math.isfinite(qty) and qty > 0) for _pid, qty in wanted):
            return {'error': 'bad_qty'}

        # The same product may sit on two lines; every id must still exist.
        product_ids = list({product_id for product_id, _qty in wanted})
        products = request.env['product.product'].sudo().browse(
            product_ids).exists()
        if len(products) != len(product_ids):
            return {'error': 'unknown_product'}
        # Only let the app order things it is allowed to see
        if any(not p.sale_ok or not p.active or not p.available_in_app
               for p in products):
            return {'error': 'product_not_orderable'}

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
        # Leave it as a quotation so staff confirm it in Odoo, or call
        # order.action_confirm() here if the app should place firm orders.
        order.message_post(body="Order placed from the mobile app.")
        return self._order_dict(order)

    def _order_dict(self, order):
        return {
            'id': order.id,
            'name': order.name,
            'date': order.date_order.isoformat() if order.date_order else '',
            'state': order.state,
            'state_label': dict(
                order._fields['state']._description_selection(order.env)
            ).get(order.state, order.state),
            'amount_total': order.amount_total,
            'currency': order.currency_id.name,
            'lines': [{
                'product': line.product_id.display_name,
                'qty': line.product_uom_qty,
                'price_unit': line.price_unit,
                'subtotal': line.price_subtotal,
            } for line in order.order_line if not line.display_type],
        }
