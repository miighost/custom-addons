"""Place an order and pay for it in one call.

    payment = "wallet"   the eWallet covers the whole order, or nothing happens
              "account"  Customer Account: confirmed and invoiced, paid later
              "waafi"    one WaafiPay charge, then confirmed, invoiced and paid

Any refusal before money moves - a cart problem, an allowance limit, a wallet
too low, a credit limit, a declined charge - rolls the whole call back, so no
stray quotation is left behind.
"""
from odoo import http
from odoo.http import request

from ..api_error import ApiError
from .main import AppApi, ROUTE, api_endpoint, wallet_cards
from .payment import charge, gateway_configured, payment_journal, settle_waafi_order


class AppCheckout(http.Controller):

    @http.route('/api/v1/payment/methods', **ROUTE)
    @api_endpoint
    def payment_methods(self, partner, payload):
        """The ways this customer can pay, for the checkout screen."""
        balance = sum(wallet_cards(partner).mapped('points'))
        commercial = partner.commercial_partner_id.sudo()
        company = partner.company_id or request.env.company
        limit = commercial.credit_limit if company.account_use_credit_limit else 0.0
        return {
            'currency': company.currency_id.name,
            'methods': [
                {'code': 'wallet', 'label': 'eWallet', 'available': balance > 0,
                 'balance': balance},
                {'code': 'account', 'label': 'Customer Account (pay later)',
                 'available': True, 'amount_owed': commercial.credit,
                 'credit_limit': limit or None,
                 'credit_available': max(limit - commercial.credit, 0.0) if limit else None},
                {'code': 'waafi', 'label': 'WaafiPay', 'available': gateway_configured()},
            ],
        }

    @http.route('/api/v1/checkout', **ROUTE)
    @api_endpoint
    def checkout(self, partner, payload):
        """Body: {"lines": [{"product_id": 42, "qty": 2}],
                  "payment": "wallet"|"account"|"waafi",
                  "phone": "25261xxxxxxx", "note": "..."}
        """
        method = (payload.get('payment') or '').lower()
        if method not in ('wallet', 'account', 'waafi'):
            raise ApiError('unknown_payment_method')

        order = AppApi()._create_app_order(partner, payload)
        order._update_programs_and_rewards()
        allowance = order._app_check_allowance()
        if allowance['blocked']:
            # Returned, not raised: the refusal is logged in Blocked Attempts,
            # and a rollback would erase that log along with the quotation.
            order.unlink()
            return {'error': 'allowance_limit_reached', 'messages': allowance['messages']}
        extra = {'allowance_warnings': allowance['warnings']} if allowance['warnings'] else {}

        if method == 'wallet':
            cards = wallet_cards(partner)
            balance = sum(cards.mapped('points'))
            total = order.amount_total
            order._app_apply_wallet(cards.filtered(lambda c: c.points > 0))
            if order.currency_id.compare_amounts(order.amount_total, 0) > 0:
                raise ApiError('insufficient_balance', amount_due=round(total, 2),
                               wallet_balance=balance,
                               missing=round(order.amount_total, 2))
            order.write({'app_payment_method': 'wallet'})
            order._app_confirm_and_invoice()
            order.message_post(body="Paid in full from the eWallet via the mobile app.")
            return {'paid': True, 'payment': 'wallet', 'order': AppApi()._order_dict(order),
                    'balance_after': sum(wallet_cards(partner).mapped('points')), **extra}

        if method == 'account':
            if order.partner_credit_warning:
                raise ApiError('credit_limit_exceeded', message=order.partner_credit_warning)
            order.write({'app_payment_method': 'account'})
            invoice = order._app_confirm_and_invoice()
            order.message_post(body="Placed from the mobile app on the customer's account (pay later).")
            return {'paid': False, 'payment': 'account', 'order': AppApi()._order_dict(order),
                    'invoice_id': invoice.id, 'amount_due': invoice.amount_residual, **extra}

        phone = (payload.get('phone') or partner.phone or '').strip()
        if not phone:
            raise ApiError('phone_required')
        if not payment_journal('waafi', partner):
            raise ApiError('payment_journal_not_configured')
        if order.currency_id.compare_amounts(order.amount_total, 0) <= 0:
            raise ApiError('nothing_to_pay')
        transaction_id = charge(phone, order.amount_total, order.currency_id.name,
                                order.name, f"{order.company_id.name} - {order.name}")
        return {**settle_waafi_order(order, transaction_id), **extra}
