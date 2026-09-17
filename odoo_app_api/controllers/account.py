"""Money the customer owes, and how they clear it.

Everything here is scoped to the commercial partner resolved from the Firebase
token. No endpoint accepts a partner id, and every invoice lookup carries the
ownership clause in its own domain - so a customer cannot read or pay another
customer's invoice by guessing an id.
"""
import logging
from datetime import date

from markupsafe import Markup

from odoo import fields, http
from odoo.http import request

from ..api_error import ApiError
from .main import ROUTE, api_endpoint, lock_for_payment, wallet_cards
from .payment import charge, payment_journal, register_payment

_logger = logging.getLogger(__name__)


def spend_wallet(cards, amount, description):
    """Take `amount` off the eWallet cards, soonest-expiring first, with a
    wallet ledger line for each card touched."""
    History = request.env['loyalty.history'].sudo()
    remaining = amount
    for card in cards.sorted(lambda c: c.expiration_date or date.max):
        if remaining <= 0:
            break
        take = min(card.points, remaining)
        if take <= 0:
            continue
        card.points -= take
        History.create({'card_id': card.id, 'description': description, 'used': take})
        remaining -= take


class AppAccount(http.Controller):

    # ------------------------------------------------------------ helpers
    def _invoice_domain(self, partner):
        return [
            ('move_type', 'in', ('out_invoice', 'out_refund')),
            ('state', '=', 'posted'),
            ('partner_id', 'child_of', partner.commercial_partner_id.id),
        ]

    def _owned_invoice(self, partner, invoice_id):
        return request.env['account.move'].sudo().search(
            self._invoice_domain(partner) + [('id', '=', int(invoice_id))],
            limit=1)

    def _invoice_dict(self, move):
        return {
            'id': move.id,
            'number': move.name,
            'type': 'refund' if move.move_type == 'out_refund' else 'invoice',
            'origin': move.invoice_origin or '',
            'date': move.invoice_date.isoformat() if move.invoice_date else '',
            'due_date': (move.invoice_date_due.isoformat()
                         if move.invoice_date_due else ''),
            'amount_total': move.amount_total,
            'amount_due': move.amount_residual,
            'currency': move.currency_id.name,
            'payment_state': move.payment_state,
            'paid': move.payment_state in ('paid', 'in_payment', 'reversed'),
            'overdue': bool(move.invoice_date_due
                            and move.amount_residual > 0
                            and move.invoice_date_due < fields.Date.today()),
        }

    # ---------------------------------------------------- home screen call
    @http.route('/api/v1/summary', **ROUTE)
    @api_endpoint
    def summary(self, partner, payload):
        """Everything the home screen needs, in one request."""
        commercial = partner.commercial_partner_id
        Move = request.env['account.move'].sudo()

        open_invoices = Move.search(
            self._invoice_domain(partner) + [('payment_state', '!=', 'paid')])
        due = sum(m.amount_residual for m in open_invoices
                  if m.move_type == 'out_invoice')
        credit_notes = sum(m.amount_residual for m in open_invoices
                           if m.move_type == 'out_refund')
        today = fields.Date.today()
        overdue = sum(m.amount_residual for m in open_invoices
                      if m.move_type == 'out_invoice'
                      and m.invoice_date_due and m.invoice_date_due < today)

        balance = sum(wallet_cards(partner).mapped('points'))
        base = (request.env['ir.config_parameter'].sudo()
                .get_param('web.base.url') or '').rstrip('/')
        code = commercial.barcode or partner.barcode or ''

        return {
            'name': partner.name,
            'partner_id': partner.id,
            'currency': (partner.company_id.currency_id.name
                         or request.env.company.currency_id.name),
            'barcode': code,
            'barcode_image_url': (
                f"{base}/report/barcode/Code128/{code}"
                "?width=600&height=150&humanreadable=1" if code else ''),
            'wallet_balance': balance,
            'total_due': round(due, 2),
            'overdue': round(overdue, 2),
            'credit_notes': round(credit_notes, 2),
            'open_invoice_count': len([m for m in open_invoices
                                       if m.move_type == 'out_invoice']),
            'can_clear_with_wallet': balance >= due > 0,
        }

    # -------------------------------------------------------- invoice list
    @http.route('/api/v1/invoices', **ROUTE)
    @api_endpoint
    def invoices(self, partner, payload):
        """Body: {"only_unpaid": true, "limit": 20, "offset": 0}"""
        domain = self._invoice_domain(partner)
        if payload.get('only_unpaid'):
            domain.append(('payment_state', '!=', 'paid'))

        Move = request.env['account.move'].sudo()
        limit = min(int(payload.get('limit', 20)), 100)
        moves = Move.search(domain, order='invoice_date desc, id desc',
                            limit=limit, offset=int(payload.get('offset', 0)))
        return {
            'total': Move.search_count(domain),
            'invoices': [self._invoice_dict(m) for m in moves],
        }

    @http.route('/api/v1/invoices/detail', **ROUTE)
    @api_endpoint
    def invoice_detail(self, partner, payload):
        """Body: {"invoice_id": 42}"""
        move = self._owned_invoice(partner, payload.get('invoice_id', 0))
        if not move:
            raise ApiError('invoice_not_found')
        data = self._invoice_dict(move)
        data['lines'] = [{
            'description': line.name or '',
            'quantity': line.quantity,
            'price_unit': line.price_unit,
            'subtotal': line.price_subtotal,
        } for line in move.invoice_line_ids if line.display_type == 'product']
        return data

    # ------------------------------------------------------ pay invoices
    @http.route('/api/v1/invoices/pay', **ROUTE)
    @api_endpoint
    def pay_invoices(self, partner, payload):
        """Pay the invoices the customer selected, in full, in one payment.

        Body: {"invoice_ids": [42, 43], "method": "wallet"|"waafi",
               "phone": "2526..."}     ("invoice_id": 42 also works)
        """
        ids = payload.get('invoice_ids') or [payload.get('invoice_id')]
        ids = {int(invoice_id) for invoice_id in ids if invoice_id}
        if not ids:
            raise ApiError('no_invoices')
        moves = request.env['account.move'].sudo().search(
            self._invoice_domain(partner) + [('id', 'in', list(ids))],
            order='invoice_date asc, id asc')
        if len(moves) != len(ids):
            raise ApiError('invoice_not_found')
        return self._pay(partner, moves, payload)

    @http.route('/api/v1/invoices/clear', **ROUTE)
    @api_endpoint
    def clear_balance(self, partner, payload):
        """Pay every open invoice at once.

        Body: {"method": "wallet"|"waafi", "phone": "2526..."}
        """
        moves = request.env['account.move'].sudo().search(
            self._invoice_domain(partner) + [
                ('move_type', '=', 'out_invoice'),
                ('payment_state', 'not in', ('paid', 'in_payment', 'reversed')),
                ('amount_residual', '>', 0),
            ], order='invoice_date asc, id asc')
        if not moves:
            return {'cleared': True, 'paid': False, 'amount_paid': 0.0, 'invoices': []}
        result = self._pay(partner, moves, payload)
        result['cleared'] = bool(result.get('paid'))
        return result

    def _pay(self, partner, moves, payload):
        """Pay `moves` in full, once: a single wallet deduction, or a single
        WaafiPay charge (one approval on the customer's phone), then one
        payment across the invoices."""
        not_payable = moves.filtered(
            lambda m: m.move_type != 'out_invoice'
            or m.currency_id.compare_amounts(m.amount_residual, 0) <= 0)
        if not_payable:
            raise ApiError('not_payable', invoices=not_payable.mapped('name'))
        if len(moves.currency_id) > 1:
            raise ApiError('mixed_currencies')
        method = (payload.get('method') or 'wallet').lower()
        if method not in ('wallet', 'waafi'):
            raise ApiError('unknown_method')
        if not lock_for_payment(moves):
            raise ApiError('payment_in_progress')
        journal = payment_journal(method, partner)
        if not journal:
            raise ApiError('payment_journal_not_configured')

        currency = moves.currency_id
        total = currency.round(sum(moves.mapped('amount_residual')))
        numbers = ", ".join(moves.mapped('name'))

        if method == 'wallet':
            cards = wallet_cards(partner)
            balance = sum(cards.mapped('points'))
            if currency.compare_amounts(balance, total) < 0:
                raise ApiError('insufficient_balance', amount_due=total,
                               wallet_balance=balance,
                               missing=currency.round(total - balance))
            spend_wallet(cards, total, f"{numbers} paid from the mobile app")
            register_payment(moves, journal, f"eWallet - {numbers}")
            for move in moves:
                move.message_post(body="Paid from the customer's eWallet via the mobile app.")
            result = {'paid': True, 'method': 'wallet', 'amount_paid': total,
                      'balance_after': sum(wallet_cards(partner).mapped('points'))}
        else:
            phone = (payload.get('phone') or partner.phone or '').strip()
            if not phone:
                raise ApiError('phone_required')
            reference = moves[0].name if len(moves) == 1 else f"{moves[0].name} +{len(moves) - 1}"
            transaction_id = charge(phone, total, currency.name, reference,
                                    f"{moves[0].company_id.name} - {numbers}")
            # The customer has been charged. If booking it fails, keep the
            # transaction id on the invoices for staff rather than rolling the
            # evidence away with the rest of the request.
            try:
                with request.env.cr.savepoint():
                    register_payment(moves, journal, f"WaafiPay {transaction_id}")
            except Exception:                                     # noqa: BLE001
                _logger.exception("Invoices %s charged (WaafiPay tx %s) but the "
                                  "payment could not be registered", numbers, transaction_id)
                for move in moves:
                    move.message_post(body=Markup(
                        "%s %s was charged through WaafiPay from the mobile app "
                        "(transaction <b>%s</b>, for %s) but the payment could not "
                        "be registered. Register it by hand.")
                        % (total, currency.name, transaction_id, numbers))
                return {'error': 'paid_not_recorded', 'transaction_id': transaction_id,
                        'amount_paid': total}
            for move in moves:
                move.message_post(body=Markup(
                    "Paid from the mobile app. WaafiPay transaction <b>%s</b>.")
                    % transaction_id)
            result = {'paid': True, 'method': 'waafi', 'amount_paid': total,
                      'transaction_id': transaction_id}

        moves.invalidate_recordset(['amount_residual', 'payment_state'])
        result['invoices'] = [self._invoice_dict(move) for move in moves]
        return result
