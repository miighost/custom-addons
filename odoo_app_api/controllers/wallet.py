"""eWallet spending and top-up.

Odoo models an eWallet as a loyalty program whose reward is a discount on the
order total. Spending it is therefore not a payment at all - it is applying a
reward to a quotation, and letting Odoo confirm the order. That keeps every
balance movement inside loyalty.history, which is what staff and accounting
actually reconcile against.
"""
import logging
from datetime import date

from odoo import fields, http
from odoo.http import request

from .main import AppApi, ROUTE, api_endpoint

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
        if order.state not in ('draft', 'sent'):
            return {'error': 'order_not_editable'}

        cards = self._active_cards(partner)
        if not cards:
            return {'error': 'no_wallet'}
        balance = sum(cards.mapped('points'))
        if balance <= 0:
            return {'error': 'insufficient_balance', 'balance': 0.0}

        total_before = order.amount_total
        applied = []

        for card in cards.sorted(
                lambda c: c.expiration_date or date.max):
            if order.amount_total <= 0:
                break
            result = order._try_apply_code(card.code)
            if isinstance(result, dict) and result.get('error'):
                if result.get('already_applied'):
                    continue
                _logger.info("Wallet %s not applicable to %s: %s",
                             card.code, order.name, result['error'])
                continue
            # result maps coupons to the rewards they make claimable
            for coupon, rewards in (result or {}).items():
                for reward in rewards:
                    outcome = order._apply_program_reward(reward, coupon)
                    if outcome.get('error'):
                        _logger.info("Reward %s rejected: %s",
                                     reward.id, outcome['error'])
                    else:
                        applied.append(card.id)

        order._update_programs_and_rewards()

        remaining = order.amount_total
        covered = total_before - remaining

        if payload.get('confirm') and remaining <= 0:
            order.action_confirm()
            order.message_post(body="Paid in full from the eWallet via the mobile app.")

        cards = self._active_cards(partner)
        return {
            'order': AppApi()._order_dict(order),
            'wallet_applied': round(covered, 2),
            'remaining_due': round(remaining, 2),
            'fully_covered': remaining <= 0,
            'balance_after': sum(cards.mapped('points')),
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
                'product_uom_qty': float(payload.get('qty', 1)),
            })],
        })
        order.message_post(body="eWallet top-up requested from the mobile app.")
        return {
            'order': AppApi()._order_dict(order),
            'note': 'Balance is credited once this order is paid and confirmed.',
        }
