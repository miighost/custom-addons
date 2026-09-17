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

from odoo import fields, http
from odoo.http import request

from ..api_error import ApiError
from .main import ROUTE, AppApi, api_endpoint, lock_for_payment, owned_order

_logger = logging.getLogger(__name__)

# Set these in Settings > Mobile App > WaafiPay
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


def gateway_configured():
    return bool(_config('url') and _config('merchant_uid'))


def charge(phone, amount, currency, reference, description):
    """Charge the customer's phone: preauthorize, then commit.

    Returns the transaction id once the money has moved. Raises ApiError when
    the gateway or the customer refuses, before anything is taken.
    """
    try:
        pre = _waafi('API_PREAUTHORIZE', {
            'paymentMethod': 'MWALLET_ACCOUNT',
            'payerInfo': {'accountNo': phone},
            'transactionInfo': {
                'referenceId': reference,
                'invoiceId': reference,
                'amount': amount,
                'currency': currency,
                'description': description,
            },
        })
    except ValueError as err:
        raise ApiError(str(err))
    except Exception:                                             # noqa: BLE001
        _logger.exception("WaafiPay preauthorize failed for %s", reference)
        raise ApiError('gateway_unreachable')

    transaction_id = (pre.get('params') or {}).get('transactionId')
    if pre.get('responseCode') != '2001' or not transaction_id:
        _logger.info("Preauthorize declined for %s: %s", reference, pre)
        raise ApiError('payment_declined',
                       gateway_message=pre.get('responseMsg') or pre.get('state') or '')

    # Money is held, not taken. Commit it.
    try:
        commit = _waafi('API_PREAUTHORIZE_COMMIT', {
            'transactionId': transaction_id,
            'description': f"Commit {reference}",
        }, timeout=COMMIT_TIMEOUT)
    except Exception:                                             # noqa: BLE001
        _logger.exception("Commit failed for %s (tx %s)", reference, transaction_id)
        raise ApiError('commit_failed', transaction_id=transaction_id)
    if commit.get('responseCode') != '2001':
        _logger.warning("Commit refused for %s: %s", reference, commit)
        raise ApiError('commit_refused', gateway_message=commit.get('responseMsg') or '')
    return transaction_id


def payment_journal(key, partner):
    """The journal a customer payment is booked through: the one chosen in
    Settings, else the first bank or cash journal of the company."""
    param = request.env['ir.config_parameter'].sudo().get_param(
        'app_api.%s_journal_id' % key)
    Journal = request.env['account.journal'].sudo()
    if param:
        journal = Journal.browse(int(param)).exists()
        if journal:
            return journal
    return Journal.search([
        ('type', 'in', ('bank', 'cash')),
        ('company_id', '=', partner.company_id.id or request.env.company.id),
    ], limit=1)


def register_payment(invoices, journal, memo):
    """Book one customer payment for `invoices` and reconcile it.

    Invoices of the same customer and account share a single payment; Odoo
    makes one per invoice where it cannot group them.
    """
    return request.env['account.payment.register'].sudo().with_context(
        active_model='account.move', active_ids=invoices.ids,
    ).create({
        'journal_id': journal.id,
        'payment_date': fields.Date.today(),
        'communication': memo,
        'group_payment': True,
    })._create_payments()


def settle_waafi_order(order, transaction_id):
    """The customer has been charged for `order`: confirm, invoice, record.

    Money has moved, so a failure past this point is reported to staff on the
    order - with the transaction id kept - and never rolled back.
    """
    order.write({'app_payment_reference': transaction_id,
                 'app_payment_method': 'waafi'})
    amount, currency = order.amount_total, order.currency_id.name
    try:
        with request.env.cr.savepoint():
            invoice = order._app_confirm_and_invoice()
            if not invoice.currency_id.is_zero(invoice.amount_residual):
                register_payment(invoice, payment_journal('waafi', order.partner_id),
                                 f"WaafiPay {transaction_id}")
    except Exception:                                             # noqa: BLE001
        _logger.exception("Order %s paid (WaafiPay tx %s) but not settled",
                          order.name, transaction_id)
        order.message_post(body=Markup(
            "Paid from the mobile app (WaafiPay transaction <b>%s</b>, %s %s) "
            "but the order could not be confirmed and invoiced automatically. "
            "Finish it by hand.") % (transaction_id, amount, currency))
        return {'error': 'paid_not_confirmed', 'transaction_id': transaction_id,
                'order': AppApi()._order_dict(order)}
    order.message_post(body=Markup(
        "Paid from the mobile app. WaafiPay transaction <b>%s</b> for %s %s.")
        % (transaction_id, amount, currency))
    return {'paid': True, 'payment': 'waafi', 'transaction_id': transaction_id,
            'order': AppApi()._order_dict(order)}


class AppPayment(http.Controller):

    @http.route('/api/v1/pay', **ROUTE)
    @api_endpoint
    def pay(self, partner, payload):
        """Charge the customer's phone for one of their quotations.

        Body: {"order_id": 123, "phone": "25261xxxxxxx"}

        The customer approves the charge on their handset. This call blocks
        until the gateway answers, so give the app a generous timeout.
        """
        order = owned_order(partner, payload.get('order_id', 0))
        if not order:
            raise ApiError('order_not_found')
        # Held until this request ends, so a second tap cannot charge again
        # while the first one waits on the customer's handset.
        if not lock_for_payment(order):
            raise ApiError('payment_in_progress')
        if order.app_payment_reference:
            raise ApiError('already_paid', transaction_id=order.app_payment_reference)
        if order.state not in ('draft', 'sent'):
            raise ApiError('order_not_payable')
        # Confirming re-evaluates loyalty and eWallet lines. Do it now, so the
        # customer is charged the total the order will actually confirm at.
        order._update_programs_and_rewards()
        if order.amount_total <= 0:
            raise ApiError('nothing_to_pay')
        phone = (payload.get('phone') or partner.phone or '').strip()
        if not phone:
            raise ApiError('phone_required')
        if not payment_journal('waafi', partner):
            raise ApiError('payment_journal_not_configured')
        allowance = order._app_check_allowance()
        if allowance['blocked']:
            # Returned, not raised, so the refusal logged in Blocked Attempts stays.
            return {'error': 'allowance_limit_reached', 'messages': allowance['messages']}

        transaction_id = charge(phone, order.amount_total, order.currency_id.name,
                                order.name, f"{order.company_id.name} - {order.name}")
        return settle_waafi_order(order, transaction_id)
