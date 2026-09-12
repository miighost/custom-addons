"""Payment from the app.

The gateway is called from ODOO, never from the app. Two reasons:

  1. the merchant API key would be extractable from any published APK/IPA;
  2. an app that reports its own payment as successful is an app that can be
     told to lie. Only the server may decide an order is paid.

So the app asks Odoo to charge the customer, Odoo talks to WaafiPay, and the
order is confirmed only on the gateway's own answer.
"""
import logging
import uuid
from datetime import datetime

import requests
from markupsafe import Markup

from odoo import http
from odoo.http import request

from .main import ROUTE, AppApi, api_endpoint, lock_for_payment

_logger = logging.getLogger(__name__)

# Set these in Settings > Technical > System Parameters
PARAMS = {
    'url': 'app_api.waafi_url',                # https://api.waafipay.net/asm
    'merchant_uid': 'app_api.waafi_merchant_uid',
    'api_user_id': 'app_api.waafi_api_user_id',
    'api_key': 'app_api.waafi_api_key',
}

# Preauthorize waits while the customer approves on their handset; commit is
# quick. Together they have to stay under Odoo's limit_time_real (120s by
# default), or a worker can be killed between the charge and the booking.
PREAUTHORIZE_TIMEOUT = 60
COMMIT_TIMEOUT = 30


def _config(name):
    return request.env['ir.config_parameter'].sudo().get_param(PARAMS[name])


def _waafi(service_name, service_params, timeout=PREAUTHORIZE_TIMEOUT):
    """One call to the gateway. Returns the decoded JSON, or raises."""
    url = _config('url')
    if not url or not _config('merchant_uid'):
        raise ValueError('payment_not_configured')

    body = {
        'schemaVersion': '1.0',
        'requestId': str(uuid.uuid4()),
        'timestamp': datetime.utcnow().isoformat(),
        'channelName': 'WEB',
        'serviceName': service_name,
        'serviceParams': dict(service_params, **{
            'merchantUid': _config('merchant_uid'),
            'apiUserId': _config('api_user_id'),
            'apiKey': _config('api_key'),
        }),
    }
    resp = requests.post(url, json=body, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


class AppPayment(http.Controller):

    def _owned_order(self, partner, order_id):
        return request.env['sale.order'].sudo().search([
            ('id', '=', int(order_id)),
            ('partner_id', 'child_of', partner.commercial_partner_id.id),
        ], limit=1)

    @http.route('/api/v1/pay', **ROUTE)
    @api_endpoint
    def pay(self, partner, payload):
        """Charge the customer's phone for one of their orders.

        Body: {"order_id": 123, "phone": "25261xxxxxxx"}

        The customer approves the charge on their handset. This call blocks
        until the gateway answers, so give the app a generous timeout.
        """
        order = self._owned_order(partner, payload.get('order_id', 0))
        if not order:
            return {'error': 'order_not_found'}
        # Held until this request ends, so a second tap cannot charge again
        # while the first one waits on the customer's handset.
        if not lock_for_payment(order):
            return {'error': 'payment_in_progress'}
        if order.app_payment_reference:
            return {'error': 'already_paid',
                    'transaction_id': order.app_payment_reference}
        if order.state not in ('draft', 'sent'):
            return {'error': 'order_not_payable'}
        # Confirming re-evaluates loyalty and eWallet lines. Do it now, so the
        # customer is charged the total the order will actually confirm at.
        order._update_programs_and_rewards()
        if order.amount_total <= 0:
            return {'error': 'nothing_to_pay'}

        phone = (payload.get('phone') or partner.phone or '').strip()
        if not phone:
            return {'error': 'phone_required'}

        amount = order.amount_total
        currency = order.currency_id.name

        try:
            pre = _waafi('API_PREAUTHORIZE', {
                'paymentMethod': 'MWALLET_ACCOUNT',
                'payerInfo': {'accountNo': phone},
                'transactionInfo': {
                    'referenceId': order.name,
                    'invoiceId': order.name,
                    'amount': amount,
                    'currency': currency,
                    'description': f"{order.company_id.name} - {order.name}",
                },
            })
        except ValueError as err:
            return {'error': str(err)}
        except Exception as err:                                  # noqa: BLE001
            _logger.exception("WaafiPay preauthorize failed for %s", order.name)
            return {'error': 'gateway_unreachable', 'detail': str(err)}

        params = pre.get('params') or {}
        transaction_id = params.get('transactionId')
        state = (pre.get('responseMsg') or pre.get('state') or '').upper()

        if pre.get('responseCode') != '2001' or not transaction_id:
            _logger.info("Preauthorize declined for %s: %s", order.name, pre)
            return {'error': 'payment_declined',
                    'gateway_message': pre.get('responseMsg') or state}

        # Money is held, not taken. Commit it.
        try:
            commit = _waafi('API_PREAUTHORIZE_COMMIT', {
                'transactionId': transaction_id,
                'description': f"Commit {order.name}",
            }, timeout=COMMIT_TIMEOUT)
        except Exception as err:                                  # noqa: BLE001
            _logger.exception("Commit failed for %s (tx %s)",
                              order.name, transaction_id)
            return {'error': 'commit_failed', 'transaction_id': transaction_id,
                    'detail': str(err)}

        if commit.get('responseCode') != '2001':
            _logger.warning("Commit refused for %s: %s", order.name, commit)
            return {'error': 'commit_refused',
                    'gateway_message': commit.get('responseMsg')}

        # The customer has been charged. Record that before anything else can
        # fail: the reference is what answers already_paid to a second call.
        order.write({
            'app_payment_reference': transaction_id,
            'app_payment_method': 'waafi',
        })
        try:
            with request.env.cr.savepoint():
                order.action_confirm()
        except Exception:                                         # noqa: BLE001
            _logger.exception("Order %s paid (WaafiPay tx %s) but not confirmed",
                              order.name, transaction_id)
            order.message_post(body=Markup(
                "Paid from the mobile app (WaafiPay transaction <b>%s</b>, "
                "%s %s) but the order could not be confirmed automatically. "
                "Confirm it by hand.") % (transaction_id, amount, currency))
            return {'error': 'paid_not_confirmed',
                    'transaction_id': transaction_id,
                    'order': AppApi()._order_dict(order)}
        order.message_post(body=Markup(
            "Paid from the mobile app. WaafiPay transaction <b>%s</b> for "
            "%s %s.") % (transaction_id, amount, currency))

        return {
            'paid': True,
            'transaction_id': transaction_id,
            'order': AppApi()._order_dict(order),
        }
