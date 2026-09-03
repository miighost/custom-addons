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

from odoo import http
from odoo.http import request

from .main import ROUTE, api_endpoint, AppApi

_logger = logging.getLogger(__name__)

# Set these in Settings > Technical > System Parameters
PARAMS = {
    'url': 'app_api.waafi_url',                # https://api.waafipay.net/asm
    'merchant_uid': 'app_api.waafi_merchant_uid',
    'api_user_id': 'app_api.waafi_api_user_id',
    'api_key': 'app_api.waafi_api_key',
}


def _config(name):
    return request.env['ir.config_parameter'].sudo().get_param(PARAMS[name])


def _waafi(service_name, service_params):
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
    resp = requests.post(url, json=body, timeout=60)
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
        if order.state not in ('draft', 'sent'):
            return {'error': 'order_not_payable'}
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
            })
        except Exception as err:                                  # noqa: BLE001
            _logger.exception("Commit failed for %s (tx %s)",
                              order.name, transaction_id)
            return {'error': 'commit_failed', 'transaction_id': transaction_id,
                    'detail': str(err)}

        if commit.get('responseCode') != '2001':
            _logger.warning("Commit refused for %s: %s", order.name, commit)
            return {'error': 'commit_refused',
                    'gateway_message': commit.get('responseMsg')}

        order.write({
            'app_payment_reference': transaction_id,
            'app_payment_method': 'waafi',
        })
        order.action_confirm()
        order.message_post(
            body=f"Paid from the mobile app. WaafiPay transaction "
                 f"<b>{transaction_id}</b> for {amount} {currency}.")

        return {
            'paid': True,
            'transaction_id': transaction_id,
            'order': AppApi()._order_dict(order),
        }
