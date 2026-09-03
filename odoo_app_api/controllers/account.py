"""Money the customer owes, and how they clear it.

Everything here is scoped to the commercial partner resolved from the Firebase
token. No endpoint accepts a partner id, and every invoice lookup carries the
ownership clause in its own domain - so a customer cannot read or pay another
customer's invoice by guessing an id.
"""
import logging

from odoo import fields, http
from odoo.http import request

from .main import ROUTE, api_endpoint
from .payment import _waafi

_logger = logging.getLogger(__name__)


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

    def _wallet_cards(self, partner):
        return request.env['loyalty.card'].sudo().search([
            ('program_type', '=', 'ewallet'),
            ('partner_id', '=', partner.commercial_partner_id.id),
            '|', ('expiration_date', '=', False),
                 ('expiration_date', '>=', fields.Date.today()),
        ])

    def _invoice_dict(self, move):
        return {
            'id': move.id,
            'number': move.name,
            'type': 'refund' if move.move_type == 'out_refund' else 'invoice',
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

    def _journal(self, key, partner):
        """The journal a customer payment is booked through."""
        param = request.env['ir.config_parameter'].sudo().get_param(
            'app_api.%s_journal_id' % key)
        Journal = request.env['account.journal'].sudo()
        if param:
            journal = Journal.browse(int(param)).exists()
            if journal:
                return journal
        # Fall back to any bank/cash journal of the right company
        return Journal.search([
            ('type', 'in', ('bank', 'cash')),
            ('company_id', '=', partner.company_id.id
                                or request.env.company.id),
        ], limit=1)

    def _register_payment(self, invoice, journal, amount, memo):
        """Book a customer payment against one invoice and reconcile it."""
        wizard = request.env['account.payment.register'].sudo().with_context(
            active_model='account.move',
            active_ids=invoice.ids,
        ).create({
            'journal_id': journal.id,
            'amount': amount,
            'payment_date': fields.Date.today(),
            'communication': memo,
        })
        return wizard._create_payments()

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

        cards = self._wallet_cards(partner)
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
            'wallet_balance': sum(cards.mapped('points')),
            'total_due': round(due, 2),
            'overdue': round(overdue, 2),
            'credit_notes': round(credit_notes, 2),
            'open_invoice_count': len([m for m in open_invoices
                                       if m.move_type == 'out_invoice']),
            'can_clear_with_wallet': sum(cards.mapped('points')) >= due > 0,
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
            return {'error': 'invoice_not_found'}
        data = self._invoice_dict(move)
        data['lines'] = [{
            'description': line.name or '',
            'quantity': line.quantity,
            'price_unit': line.price_unit,
            'subtotal': line.price_subtotal,
        } for line in move.invoice_line_ids if line.display_type == 'product']
        return data

    # ------------------------------------------------------ pay an invoice
    @http.route('/api/v1/invoices/pay', **ROUTE)
    @api_endpoint
    def pay_invoice(self, partner, payload):
        """Body: {"invoice_id": 42, "method": "wallet"|"waafi",
                  "amount": 0, "phone": "2526..."}

        `amount` is optional - leave it out to pay the invoice in full.
        """
        move = self._owned_invoice(partner, payload.get('invoice_id', 0))
        if not move:
            return {'error': 'invoice_not_found'}
        if move.move_type != 'out_invoice':
            return {'error': 'not_payable'}
        if move.payment_state == 'paid' or move.amount_residual <= 0:
            return {'error': 'already_paid'}

        method = (payload.get('method') or 'wallet').lower()
        amount = float(payload.get('amount') or 0) or move.amount_residual
        amount = min(round(amount, 2), move.amount_residual)
        if amount <= 0:
            return {'error': 'invalid_amount'}

        if method == 'wallet':
            return self._pay_from_wallet(partner, move, amount)
        if method == 'waafi':
            return self._pay_from_gateway(partner, move, amount, payload)
        return {'error': 'unknown_method'}

    # ---- wallet ---------------------------------------------------------
    def _pay_from_wallet(self, partner, move, amount):
        cards = self._wallet_cards(partner)
        balance = sum(cards.mapped('points'))
        if balance <= 0:
            return {'error': 'insufficient_balance', 'balance': 0.0}
        amount = min(amount, balance)

        journal = self._journal('wallet', partner)
        if not journal:
            return {'error': 'wallet_journal_not_configured'}

        # Take the money off the cards first, oldest expiry first.
        remaining = amount
        History = request.env['loyalty.history'].sudo()
        for card in cards.sorted(lambda c: (c.expiration_date or fields.Date.max)):
            if remaining <= 0:
                break
            take = min(card.points, remaining)
            if take <= 0:
                continue
            card.points -= take
            History.create({
                'card_id': card.id,
                'description': f"Invoice {move.name} paid from the mobile app",
                'used': take,
            })
            remaining -= take

        self._register_payment(move, journal, amount,
                               f"eWallet - {move.name}")
        move.message_post(
            body=f"{amount} {move.currency_id.name} paid from the customer's "
                 f"eWallet via the mobile app.")

        cards = self._wallet_cards(partner)
        move.invalidate_recordset(['amount_residual', 'payment_state'])
        return {
            'paid': True,
            'method': 'wallet',
            'amount_paid': amount,
            'balance_after': sum(cards.mapped('points')),
            'invoice': self._invoice_dict(move),
        }

    # ---- gateway --------------------------------------------------------
    def _pay_from_gateway(self, partner, move, amount, payload):
        phone = (payload.get('phone') or partner.phone or '').strip()
        if not phone:
            return {'error': 'phone_required'}

        journal = self._journal('waafi', partner)
        if not journal:
            return {'error': 'payment_journal_not_configured'}

        try:
            pre = _waafi('API_PREAUTHORIZE', {
                'paymentMethod': 'MWALLET_ACCOUNT',
                'payerInfo': {'accountNo': phone},
                'transactionInfo': {
                    'referenceId': move.name,
                    'invoiceId': move.name,
                    'amount': amount,
                    'currency': move.currency_id.name,
                    'description': f"{move.company_id.name} - {move.name}",
                },
            })
        except ValueError as err:
            return {'error': str(err)}
        except Exception as err:                                  # noqa: BLE001
            _logger.exception("Gateway unreachable for %s", move.name)
            return {'error': 'gateway_unreachable', 'detail': str(err)}

        transaction_id = (pre.get('params') or {}).get('transactionId')
        if pre.get('responseCode') != '2001' or not transaction_id:
            return {'error': 'payment_declined',
                    'gateway_message': pre.get('responseMsg')}

        try:
            commit = _waafi('API_PREAUTHORIZE_COMMIT', {
                'transactionId': transaction_id,
                'description': f"Commit {move.name}",
            })
        except Exception as err:                                  # noqa: BLE001
            _logger.exception("Commit failed for %s (tx %s)",
                              move.name, transaction_id)
            return {'error': 'commit_failed', 'transaction_id': transaction_id}

        if commit.get('responseCode') != '2001':
            return {'error': 'commit_refused',
                    'gateway_message': commit.get('responseMsg')}

        self._register_payment(move, journal, amount,
                               f"WaafiPay {transaction_id}")
        move.message_post(
            body=f"{amount} {move.currency_id.name} paid from the mobile app. "
                 f"WaafiPay transaction <b>{transaction_id}</b>.")
        move.invalidate_recordset(['amount_residual', 'payment_state'])
        return {
            'paid': True,
            'method': 'waafi',
            'amount_paid': amount,
            'transaction_id': transaction_id,
            'invoice': self._invoice_dict(move),
        }

    # --------------------------------------------------- clear everything
    @http.route('/api/v1/invoices/clear', **ROUTE)
    @api_endpoint
    def clear_balance(self, partner, payload):
        """Pay off every open invoice, oldest first.

        Body: {"method": "wallet"|"waafi", "phone": "2526..."}
        """
        method = (payload.get('method') or 'wallet').lower()
        moves = request.env['account.move'].sudo().search(
            self._invoice_domain(partner) + [
                ('move_type', '=', 'out_invoice'),
                ('payment_state', '!=', 'paid'),
            ], order='invoice_date asc, id asc')
        if not moves:
            return {'cleared': True, 'paid': [], 'message': 'nothing_due'}

        paid, failed = [], []
        for move in moves:
            if move.amount_residual <= 0:
                continue
            result = (self._pay_from_wallet(partner, move, move.amount_residual)
                      if method == 'wallet'
                      else self._pay_from_gateway(partner, move,
                                                  move.amount_residual, payload))
            if result.get('paid'):
                paid.append({'number': move.name,
                             'amount': result['amount_paid']})
            else:
                failed.append({'number': move.name,
                               'error': result.get('error'),
                               'gateway_message': result.get('gateway_message')})
                break        # stop at the first failure, do not keep charging

        cards = self._wallet_cards(partner)
        still_open = request.env['account.move'].sudo().search_count(
            self._invoice_domain(partner) + [
                ('move_type', '=', 'out_invoice'),
                ('payment_state', '!=', 'paid'),
            ])
        return {
            'cleared': not failed,
            'paid': paid,
            'failed': failed,
            'invoices_still_open': still_open,
            'wallet_balance': sum(cards.mapped('points')),
        }
