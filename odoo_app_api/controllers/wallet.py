"""eWallet spending and top-up.

Odoo models an eWallet as a loyalty program whose reward is a discount on the
order total. Spending it is therefore not a payment at all - it is applying a
reward to a quotation, and letting Odoo confirm the order. That keeps every
balance movement inside loyalty.history, which is what staff and accounting
actually reconcile against.
"""
import logging
import math

from odoo import fields, http
from odoo.http import request

from .main import AppApi, ROUTE, api_endpoint, lock_for_payment

_logger = logging.getLogger(__name__)


class AppWallet(http.Controller):

    # ------------------------------------------------------------------
    def _active_cards(self, partner):
        return request.env['loyalty.card'].sudo().search([
            ('program_type', '=', 'ewallet'),
            ('partner_id', '=', partner.commercial_partner_id.id),
            '|', ('expiration_date', '=', False),
                 ('expiration_date', '>=', fields.Date.today()),
        ])

    def _owned_order(self, partner, order_id):
        """Never browse an id straight from the app - scope it to the caller."""
        return request.env['sale.order'].sudo().search([
            ('id', '=', int(order_id)),
            ('partner_id', 'child_of', partner.commercial_partner_id.id),
        ], limit=1)

    # ------------------------------------------------------- pay an order
    @http.route('/api/v1/wallet/pay', **ROUTE)
    @api_endpoint
    def wallet_pay(self, partner, payload):
        """Apply the customer's eWallet to one of their quotations.

        Body: {"order_id": 123, "confirm": true}
        """
        order = self._owned_order(partner, payload.get('order_id', 0))
        if not order:
            return {'error': 'order_not_found'}
        if not lock_for_payment(order):
            return {'error': 'payment_in_progress'}
        if order.state not in ('draft', 'sent'):
            return {'error': 'order_not_editable'}

        cards = self._active_cards(partner)
        if not cards:
            return {'error': 'no_wallet'}
        if sum(cards.mapped('points')) <= 0:
            return {'error': 'insufficient_balance', 'balance': 0.0}

        order._app_apply_wallet(cards.filtered(lambda c: c.points > 0))

        # Measured from the reward lines, so calling this twice on the same
        # quotation still reports what the wallet covers.
        applied = -sum(order.order_line.filtered(
            lambda line: line.coupon_id in cards).mapped('price_total'))
        if not applied:
            _logger.info("No eWallet reward applicable to %s", order.name)
        remaining = order.amount_total
        fully_covered = order.currency_id.compare_amounts(remaining, 0) <= 0

        if payload.get('confirm') and fully_covered:
            order.write({'app_payment_method': 'wallet'})
            order.action_confirm()
            order.message_post(body="Paid in full from the eWallet via the mobile app.")

        return {
            'order': AppApi()._order_dict(order),
            'wallet_applied': round(applied, 2),
            'remaining_due': round(max(remaining, 0.0), 2),
            'fully_covered': fully_covered,
            # Points leave the card when the order is confirmed; until then
            # this is what will be left once it is.
            'balance_after': sum(order._get_real_points_for_coupon(card)
                                 for card in cards),
            'confirmed': order.state in ('sale', 'done'),
        }

    # ------------------------------------------------------------ top-up
    @http.route('/api/v1/wallet/topup/products', **ROUTE)
    @api_endpoint
    def topup_products(self, partner, payload):
        """The top-up products configured on the active eWallet programs."""
        programs = request.env['loyalty.program'].sudo().search([
            ('program_type', '=', 'ewallet'), ('active', '=', True),
        ])
        products = programs.mapped('trigger_product_ids').filtered(
            lambda p: p.active and p.sale_ok)
        return {'products': [{
            'id': p.id,
            'name': p.display_name,
            'amount': p.list_price,
            'currency': p.currency_id.name,
        } for p in products]}

    @http.route('/api/v1/wallet/topup', **ROUTE)
    @api_endpoint
    def topup(self, partner, payload):
        """Create a top-up order. The balance is credited when it is PAID -
        do not confirm this from the app without a real payment.

        Body: {"product_id": 55, "qty": 1}
        """
        qty = float(payload.get('qty', 1))
        if not (math.isfinite(qty) and qty > 0):
            return {'error': 'bad_qty'}
        product = request.env['product.product'].sudo().browse(
            int(payload.get('product_id', 0))).exists()
        if not product:
            return {'error': 'unknown_product'}

        programs = request.env['loyalty.program'].sudo().search([
            ('program_type', '=', 'ewallet'), ('active', '=', True),
        ])
        if product not in programs.mapped('trigger_product_ids'):
            return {'error': 'not_a_topup_product'}

        order = request.env['sale.order'].sudo().create({
            'partner_id': partner.id,
            'is_app_order': True,
            'origin': 'Mobile app - eWallet top-up',
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': qty,
            })],
        })
        order.message_post(body="eWallet top-up requested from the mobile app.")
        return {
            'order': AppApi()._order_dict(order),
            'note': 'Balance is credited once this order is paid and confirmed.',
        }
