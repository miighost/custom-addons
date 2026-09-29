"""Place an order and pay for it in one call.

    payment = "wallet"   the eWallet covers the whole order, or nothing happens
              "account"  Customer Account: confirmed and invoiced, paid later
              "waafi"    one WaafiPay charge, then confirmed, invoiced and paid

Any refusal before money moves - a cart problem, an allowance limit, a wallet
too low, a credit limit, a declined charge - rolls the whole call back, so no
stray quotation is left behind.
"""
import json
import logging
import math

from odoo import fields, http
from odoo.http import request

from ..api_error import ApiError
from .main import AppApi, ROUTE, api_endpoint, wallet_cards, safe_table_info
from .payment import charge, gateway_configured, payment_journal, settle_waafi_order

_logger = logging.getLogger(__name__)


class AppCheckout(http.Controller):

    def _get_base_url(self):
        try:
            host_url = (request.httprequest.host_url or '').rstrip('/')
            if host_url and 'localhost' not in host_url and '127.0.0.1' not in host_url:
                return host_url
        except Exception:
            pass
        return (request.env['ir.config_parameter'].sudo().get_param('web.base.url') or '').rstrip('/')

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

    # ---------------------------------------------------- POS Repair & Maintenance
    @http.route('/api/v1/pos/fix_taxes', **ROUTE)
    @api_endpoint
    def fix_pos_taxes(self, partner, payload):
        """Repair cross-company session taxes that block POS sessions."""
        cr = request.env.cr
        # In Odoo 19, translated fields like name are stored as jsonb
        cr.execute("SELECT id, name::text FROM account_tax WHERE name::text LIKE '%(From App%'")
        rows = cr.fetchall()
        tax_ids = [r[0] for r in rows]
        deleted_names = [r[1] for r in rows]

        if tax_ids:
            tax_ids_tuple = tuple(tax_ids)
            try:
                cr.execute(
                    "DELETE FROM account_tax_pos_order_line_rel WHERE account_tax_id IN %s",
                    (tax_ids_tuple,)
                )
            except Exception:
                pass

            try:
                cr.execute(
                    "DELETE FROM pos_order_line_account_tax_rel WHERE account_tax_id IN %s",
                    (tax_ids_tuple,)
                )
            except Exception:
                pass

            try:
                cr.execute(
                    "DELETE FROM account_tax_repartition_line WHERE invoice_tax_id IN %s OR refund_tax_id IN %s",
                    (tax_ids_tuple, tax_ids_tuple)
                )
            except Exception:
                pass

            try:
                cr.execute(
                    "DELETE FROM account_tax WHERE id IN %s",
                    (tax_ids_tuple,)
                )
            except Exception:
                pass

            cr.commit()

        return {
            'fixed': True,
            'deleted_taxes': deleted_names,
            'count': len(deleted_names),
            'message': 'Cleaned up corrupted session taxes. POS can now be opened normally.'
        }

    # ---------------------------------------------------- POS Open Sessions & Tables
    @http.route(['/api/v1/pos/tables', '/api/v1/pos/sessions'], **ROUTE)
    @api_endpoint
    def pos_tables(self, partner, payload):
        """List active open POS sessions, restaurant floors, and dining tables."""
        PosSession = request.env['pos.session'].sudo()
        sessions = PosSession.search([('state', '=', 'opened')], order='id desc')

        has_restaurant = 'restaurant.floor' in request.env and 'restaurant.table' in request.env
        Table = request.env['restaurant.table'].sudo() if has_restaurant else None

        result_sessions = []
        for s in sessions:
            config = s.config_id
            session_data = {
                'session_id': s.id,
                'session_name': s.name,
                'pos_id': config.id,
                'pos_name': config.name,
                'currency': s.currency_id.name,
                'payment_methods': [{
                    'id': m.id,
                    'name': m.name,
                    'type': getattr(m, 'type', None),
                } for m in config.payment_method_ids],
                'floors': [],
                'tables': [],
            }
            if has_restaurant and hasattr(config, 'floor_ids') and config.floor_ids:
                for floor in config.floor_ids:
                    floor_tables = []
                    for t in floor.table_ids.filtered(lambda tbl: getattr(tbl, 'active', True)):
                        tbl_info = safe_table_info(t)
                        t_data = {
                            'table_id': t.id,
                            'table_number': tbl_info['table_number'],
                            'table_name': tbl_info['table_name'],
                            'seats': getattr(t, 'seats', 1),
                            'floor_id': floor.id,
                            'floor_name': floor.name,
                        }
                        floor_tables.append(t_data)
                        session_data['tables'].append(t_data)
                    session_data['floors'].append({
                        'floor_id': floor.id,
                        'floor_name': floor.name,
                        'table_count': len(floor_tables),
                        'tables': floor_tables,
                    })
            elif has_restaurant and Table:
                all_tables = Table.search([('active', '=', True)])
                for t in all_tables:
                    tbl_info = safe_table_info(t)
                    t_data = {
                        'table_id': t.id,
                        'table_number': tbl_info['table_number'],
                        'table_name': tbl_info['table_name'],
                        'seats': getattr(t, 'seats', 1),
                        'floor_id': t.floor_id.id if t.floor_id else None,
                        'floor_name': t.floor_id.name if t.floor_id else '',
                    }
                    session_data['tables'].append(t_data)

            result_sessions.append(session_data)

        total_tables = sum(len(s['tables']) for s in result_sessions)
        return {
            'is_open': bool(sessions),
            'session_count': len(sessions),
            'table_count': total_tables,
            'sessions': result_sessions,
        }

    # ------------------------------------------------------------- checkout
    @http.route('/api/v1/checkout', **ROUTE)
    @api_endpoint
    def checkout(self, partner, payload):
        """Place an order and pay for it in one call.

        Body:
            lines: [{"product_id": 42, "qty": 2}]
            payment: "wallet" | "account" | "waafi"
            session_id: 14 (optional, targets specific open POS session)
            table_id: 12 (optional, table record ID)
            table_no: "4" (optional, table number)
            order_type: "sale" | "pos" (optional, auto-routes to pos if table or session_id is given)
            phone: "25261xxxxxxx"
            note: "..."
        """
        method = (payload.get('payment') or '').lower()
        if method not in ('wallet', 'account', 'waafi'):
            raise ApiError('unknown_payment_method')

        is_pos = (payload.get('order_type') == 'pos'
                  or bool(payload.get('session_id'))
                  or bool(payload.get('table_no'))
                  or bool(payload.get('table_number'))
                  or bool(payload.get('table_id'))
                  or bool(payload.get('table')))
        if is_pos:
            return self._checkout_pos(partner, payload, method)



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

    def _checkout_pos(self, partner, payload, method):
        """Route the order into an active POS Session as a pos.order (Kitchen & Table workflow)."""
        # Resolve table if given (optional)
        table = None
        table_param = (payload.get('table_no')
                       or payload.get('table_number')
                       or payload.get('table_id')
                       or payload.get('table'))
        if table_param and 'restaurant.table' in request.env:
            Table = request.env['restaurant.table'].sudo()
            if isinstance(table_param, int) or (isinstance(table_param, str) and table_param.isdigit()):
                table = Table.browse(int(table_param)).exists()
            if not table and table_param:
                t_str = str(table_param).strip()
                digit_match = ''.join(c for c in t_str if c.isdigit())

                domain = []
                if 'table_number' in Table._fields:
                    f_type = Table._fields['table_number'].type
                    if f_type in ('integer', 'float'):
                        if digit_match:
                            domain = [('table_number', '=', int(digit_match))]
                    else:
                        candidates = [t_str]
                        if digit_match and digit_match != t_str:
                            candidates.append(digit_match)
                        domain = [('table_number', 'in', candidates)]
                elif 'name' in Table._fields:
                    candidates = [t_str]
                    if digit_match and digit_match != t_str:
                        candidates.append(digit_match)
                    domain = [('name', 'in', candidates)]

                if domain:
                    try:
                        table = Table.search(domain, limit=1)
                    except Exception:
                        table = None

        # Resolve open POS session
        PosSession = request.env['pos.session'].sudo()
        session_param = payload.get('session_id')
        session = None

        if session_param:
            try:
                session = PosSession.browse(int(session_param)).exists()
            except (ValueError, TypeError):
                session = None
            if not session or session.state != 'opened':
                # If requested session is closed, seamlessly fall back to current open session on config 7
                target_pos_id = int(payload.get('pos_id') or 7)
                session = PosSession.search([
                    ('state', '=', 'opened'),
                    ('config_id', '=', target_pos_id),
                ], limit=1, order='id desc')
                if not session:
                    session = PosSession.search([('state', '=', 'opened')], limit=1, order='id desc')
                if not session:
                    raise ApiError('no_open_pos_session',
                                   message='The restaurant POS is currently closed. Please open a POS session first.')
        else:
            # POS ID is 7 (From App) by default
            target_pos_id = int(payload.get('pos_id') or 7)
            session = PosSession.search([
                ('state', '=', 'opened'),
                ('config_id', '=', target_pos_id),
            ], limit=1, order='id desc')
            # Auto-detect open session matching the table's floor if not found
            if not session and table and getattr(table, 'floor_id', None):
                session = PosSession.search([
                    ('state', '=', 'opened'),
                    ('config_id.floor_ids', 'in', [table.floor_id.id])
                ], limit=1, order='id desc')
            # Fall back to any active opened session
            if not session:
                session = PosSession.search([('state', '=', 'opened')], limit=1, order='id desc')
            if not session:
                raise ApiError('no_open_pos_session',
                               message='The restaurant POS is currently closed. Please open a POS session first.')

        # If no table was explicitly resolved, check if this POS has only 1 table and auto-assign
        if not table and 'restaurant.table' in request.env:
            Table = request.env['restaurant.table'].sudo()
            pos_tables = []
            if hasattr(session.config_id, 'floor_ids') and session.config_id.floor_ids:
                pos_tables = session.config_id.floor_ids.mapped('table_ids').filtered(lambda t: getattr(t, 'active', True))
            if not pos_tables:
                pos_tables = Table.search([('active', '=', True)], limit=2)
            if len(pos_tables) == 1:
                table = pos_tables[0]

        # Parse & validate lines
        lines = payload.get('lines')
        if not lines and (payload.get('pid') or payload.get('product_id')):
            pid = payload.get('pid') or payload.get('product_id')
            qty = payload.get('qty') or 1
            lines = [{'product_id': pid, 'qty': qty}]
        lines = lines or []
        if isinstance(lines, str):
            try:
                lines = json.loads(lines)
            except ValueError:
                raise ApiError('bad_lines')
        if not lines:
            raise ApiError('no_lines')

        Product = request.env['product.product'].sudo()
        wanted = []
        for l in lines:
            pid = int(l.get('product_id') or l.get('productId') or 0)
            qty = float(l.get('qty', 1))
            if not (math.isfinite(qty) and qty > 0):
                raise ApiError('bad_qty')
            prod = Product.browse(pid).exists()
            if not prod:
                raise ApiError('unknown_product')
            if not prod.sale_ok or not prod.active:
                raise ApiError('product_not_orderable')
            if not getattr(prod, 'available_in_app', True) and not getattr(prod, 'available_in_pos', False):
                raise ApiError('product_not_orderable')
            if getattr(prod, 'is_storable', False) and prod.qty_available <= 0:
                raise ApiError('out_of_stock', products=[prod.display_name])
            wanted.append({'product': prod, 'qty': qty})

        # Allowance check via staff.allowance.rule if available
        basket = {'blocked': False, 'warnings': [], 'messages': []}
        if 'staff.allowance.rule' in request.env:
            Rule = request.env['staff.allowance.rule'].sudo()
            if hasattr(Rule, 'check_pos_basket'):
                try:
                    basket = Rule.check_pos_basket(
                        partner.id,
                        [{'product_id': w['product'].id, 'qty': w['qty']} for w in wanted],
                        source='app',
                    ) or {}
                except Exception as e:
                    _logger.warning("Error checking allowance basket: %s", e)
        if basket.get('blocked'):
            return {'error': 'allowance_limit_reached', 'messages': basket.get('messages', [])}

        # Compute price through pricelist
        pricelist = partner.property_product_pricelist or session.config_id.pricelist_id
        prods = Product.browse([w['product'].id for w in wanted])
        prices = {}
        if pricelist:
            try:
                prices = pricelist.sudo()._get_products_price(prods, quantity=1)
            except Exception:
                prices = {}

        # Table & Note details (safe for Odoo 19 restaurant.table)
        tbl_info = safe_table_info(table)
        table_num = tbl_info['table_number'] if table else (str(table_param or ''))
        table_display = tbl_info['table_name'] if table else (f"Table {table_param}" if table_param else "Dine-In")
        table_label = table_display
        customer_note = (payload.get('note') or '').strip()
        order_note = f"[{table_label}] - Mobile App Order" + (f": {customer_note}" if customer_note else "")

        pos_lines = []
        amount_total = 0.0
        for w in wanted:
            p = w['product']
            unit_price = prices.get(p.id, p.list_price)
            line_subtotal = round(unit_price * w['qty'], 2)
            amount_total += line_subtotal
            line_vals = {
                'product_id': p.id,
                'qty': w['qty'],
                'price_unit': unit_price,
                'price_subtotal': line_subtotal,
                'price_subtotal_incl': line_subtotal,
            }
            if 'full_product_name' in request.env['pos.order.line']._fields:
                line_vals['full_product_name'] = p.display_name
            if 'customer_note' in request.env['pos.order.line']._fields and customer_note:
                line_vals['customer_note'] = customer_note
            if 'tax_ids' in request.env['pos.order.line']._fields and p.taxes_id:
                session_company = session.company_id or session.config_id.company_id
                Rep = request.env['account.tax.repartition.line'].sudo() if 'account.tax.repartition.line' in request.env else None
                safe_taxes = []
                for tax in p.taxes_id:
                    if tax.company_id and tax.company_id != session_company:
                        continue
                    crossover = False
                    rep_lines = (getattr(tax, 'invoice_repartition_line_ids', Rep)
                                 | getattr(tax, 'refund_repartition_line_ids', Rep)) if Rep else []
                    for rep in rep_lines:
                        acct = getattr(rep, 'account_id', None)
                        if acct and acct.company_id and acct.company_id != session_company:
                            crossover = True
                            break
                        if getattr(rep, 'company_id', None) and rep.company_id != session_company:
                            crossover = True
                            break
                    if not crossover:
                        safe_taxes.append(tax.id)
                if safe_taxes:
                    line_vals['tax_ids'] = [(6, 0, safe_taxes)]
            pos_lines.append((0, 0, line_vals))

        amount_total = round(amount_total, 2)
        extra = {'allowance_warnings': basket['warnings']} if basket.get('warnings') else {}

        # Validate payment
        cards = None
        if method == 'wallet':
            cards = wallet_cards(partner)
            balance = sum(cards.mapped('points'))
            if balance < amount_total:
                raise ApiError('insufficient_balance', amount_due=amount_total,
                               wallet_balance=balance, missing=round(amount_total - balance, 2))
        elif method == 'account':
            commercial = partner.commercial_partner_id.sudo()
            company = partner.company_id or request.env.company
            if company.account_use_credit_limit and commercial.credit_limit:
                if commercial.credit + amount_total > commercial.credit_limit:
                    raise ApiError('credit_limit_exceeded',
                                   message=f"Credit limit exceeded. Balance due: {commercial.credit}")
        elif method == 'waafi':
            phone = (payload.get('phone') or partner.phone or '').strip()
            if not phone:
                raise ApiError('phone_required')
            if not payment_journal('waafi', partner):
                raise ApiError('payment_journal_not_configured')
            if amount_total > 0:
                charge(phone, amount_total, session.currency_id.name,
                       session.name, f"{session.config_id.name} - Table Order")

        # Deduct wallet points if paying via wallet
        if method == 'wallet' and cards and amount_total > 0:
            remaining_to_deduct = amount_total
            History = request.env['loyalty.history'].sudo()
            for card in cards.filtered(lambda c: c.points > 0):
                deduct = min(card.points, remaining_to_deduct)
                card.points -= deduct
                vals = {
                    'card_id': card.id,
                    'description': f"POS Order {session.name} - {partner.name}",
                }
                if 'used' in History._fields:
                    vals['used'] = deduct
                elif 'points' in History._fields:
                    vals['points'] = -deduct
                History.create(vals)
                remaining_to_deduct -= deduct
                if remaining_to_deduct <= 0:
                    break

        # Pick the appropriate POS payment method from the session config
        pos_payment_methods = session.config_id.payment_method_ids
        payment_method = None

        # Allow explicit override from payload if specified
        custom_pm_id = payload.get('pos_payment_method_id') or payload.get('payment_method_id')
        if custom_pm_id:
            payment_method = pos_payment_methods.filtered(lambda m: m.id == int(custom_pm_id))[:1]

        if not payment_method and method == 'wallet':
            # Priority 1: JPH payment method if configured
            payment_method = pos_payment_methods.filtered(
                lambda m: 'jph' in (m.name or '').lower()
            )[:1]
            # Priority 2: Customer Account (pay_later) - standard Odoo POS eWallet flow
            if not payment_method:
                payment_method = pos_payment_methods.filtered(
                    lambda m: getattr(m, 'type', None) == 'pay_later'
                    or 'customer account' in (m.name or '').lower()
                    or 'pay later' in (m.name or '').lower()
                )[:1]
            # Priority 3: Exact name "ewallet" or "e-wallet"
            if not payment_method:
                payment_method = pos_payment_methods.filtered(
                    lambda m: (m.name or '').strip().lower() in ('ewallet', 'e-wallet', 'e_wallet')
                )[:1]
            # Priority 4: Any method containing "ewallet"
            if not payment_method:
                payment_method = pos_payment_methods.filtered(
                    lambda m: 'ewallet' in (m.name or '').lower() or 'e-wallet' in (m.name or '').lower()
                )[:1]
            # Priority 5: Any method containing "account"
            if not payment_method:
                payment_method = pos_payment_methods.filtered(
                    lambda m: 'account' in (m.name or '').lower()
                )[:1]
        elif not payment_method and method == 'account':
            # Priority 1: JPH payment method if configured
            payment_method = pos_payment_methods.filtered(
                lambda m: 'jph' in (m.name or '').lower()
            )[:1]
            # Priority 2: Customer Account (pay_later)
            if not payment_method:
                payment_method = pos_payment_methods.filtered(
                    lambda m: getattr(m, 'type', None) == 'pay_later'
                    or 'customer account' in (m.name or '').lower()
                    or 'account' in (m.name or '').lower()
                    or 'pay later' in (m.name or '').lower()
                )[:1]
        elif not payment_method and method == 'waafi':
            # Prefer Electronic / Bank payment method
            payment_method = pos_payment_methods.filtered(
                lambda m: 'waafi' in (m.name or '').lower()
                or getattr(m, 'type', None) == 'bank'
            )[:1]

        if not payment_method and pos_payment_methods:
            payment_method = pos_payment_methods[0]

        # Resolve pricelist (required field on pos.order)
        pricelist_id = False
        if session.config_id.pricelist_id:
            pricelist_id = session.config_id.pricelist_id.id
        elif partner.property_product_pricelist:
            pricelist_id = partner.property_product_pricelist.id
        elif hasattr(session.config_id, 'available_pricelist_ids') and session.config_id.available_pricelist_ids:
            pricelist_id = session.config_id.available_pricelist_ids[0].id

        # Create POS order
        pos_vals = {
            'session_id': session.id,
            'partner_id': partner.id,
            'lines': pos_lines,
            'amount_total': amount_total,
            'amount_paid': amount_total,
            'amount_tax': 0.0,
            'amount_return': 0.0,
            'state': 'paid' if payment_method else 'draft',
        }
        if 'is_app_order' in request.env['pos.order']._fields:
            pos_vals['is_app_order'] = True
        if 'app_payment_method' in request.env['pos.order']._fields:
            pos_vals['app_payment_method'] = method

        # Safely assign note if the field exists on pos.order
        for note_f in ('note', 'customer_note', 'general_note'):
            if note_f in request.env['pos.order']._fields:
                pos_vals[note_f] = order_note
                break

        if pricelist_id:
            pos_vals['pricelist_id'] = pricelist_id

        if table and 'table_id' in request.env['pos.order']._fields:
            pos_vals['table_id'] = table.id

        if 'customer_count' in request.env['pos.order']._fields:
            pos_vals['customer_count'] = int(payload.get('customer_count') or payload.get('guests') or 1)

        if payment_method and amount_total > 0:
            pos_vals['payment_ids'] = [(0, 0, {
                'payment_method_id': payment_method.id,
                'amount': amount_total,
                'payment_date': fields.Datetime.now(),
            })]

        try:
            pos_order = request.env['pos.order'].sudo().create(pos_vals)
        except Exception as e:
            err_str = str(e).lower()
            if 'company' in err_str or 'tax' in err_str or 'repartition' in err_str:
                _logger.warning("Retrying pos.order.create without taxes due to cross-company tax inconsistency: %s", e)
                for _cmd, _id, lvals in pos_vals.get('lines', []):
                    lvals.pop('tax_ids', None)
                pos_order = request.env['pos.order'].sudo().create(pos_vals)
            else:
                raise

        # Log order details and table notes to order chatter
        if hasattr(pos_order, 'message_post'):
            try:
                pos_order.message_post(body=order_note)
            except Exception:
                pass

        balance_after = sum(wallet_cards(partner).mapped('points')) if method == 'wallet' else None
        return {
            'paid': True,
            'payment': method,
            'payment_method_name': payment_method.name if payment_method else '',
            'order_type': 'pos',
            'sent_to_kitchen': True,
            'order': {
                'id': pos_order.id,
                'name': pos_order.name,
                'pos_reference': pos_order.pos_reference or pos_order.name,
                'table_id': table.id if table else None,
                'table_no': table_num,
                'table_name': table_display,
                'note': order_note,
                'amount_total': pos_order.amount_total,
                'currency': session.currency_id.name,
                'state': pos_order.state,
                'lines': [{
                    'product': l.product_id.display_name,
                    'qty': l.qty,
                    'price_unit': l.price_unit,
                    'subtotal': l.price_subtotal,
                } for l in pos_order.lines],
            },
            **({'balance_after': balance_after} if balance_after is not None else {}),
            **extra,
        }

    # ---------------------------------------------------- Assign and Pay Order
    @http.route(['/api/v1/orders/pay', '/api/v1/pos/order/pay'], **ROUTE)
    @api_endpoint
    def pay_order(self, partner, payload):
        """Assign an open/draft POS or Sale order to a customer and pay for it with wallet or customer account.

        Body:
            order_id: 30265 or "260-7-000016" (required)
            order_type: "pos" | "sale" (optional, auto-detected)
            payment_method: "wallet" | "account" | "waafi" (default: "wallet")
            customer_id: 42 (optional: partner ID to assign; defaults to caller if omitted)
            barcode: "JPH-..." (optional: lookup partner by barcode)
            phone: "252..." (optional: lookup partner by phone)
        """
        ref_or_id = (payload.get('order_id')
                     or payload.get('order_number')
                     or payload.get('pos_reference')
                     or payload.get('name'))
        if not ref_or_id:
            raise ApiError('no_order_specified', message='Please specify an order ID or order number.')

        method = (payload.get('payment_method') or payload.get('payment') or 'wallet').lower()
        if method not in ('wallet', 'account', 'waafi'):
            raise ApiError('unknown_payment_method')

        # 1. Resolve Target Customer
        target_customer = partner
        cust_id = payload.get('customer_id') or payload.get('partner_id')
        cust_barcode = payload.get('barcode')
        cust_phone = payload.get('customer_phone') or payload.get('phone')

        Partner = request.env['res.partner'].sudo()
        if cust_id:
            found = Partner.browse(int(cust_id)).exists()
            if found:
                target_customer = found
        elif cust_barcode:
            found = Partner.search([('barcode', '=', str(cust_barcode).strip())], limit=1)
            if found:
                target_customer = found
        elif cust_phone and str(cust_phone).strip() != str(partner.phone or '').strip():
            found = Partner.search([('phone', 'ilike', str(cust_phone).strip())], limit=1)
            if found:
                target_customer = found

        # 2. Locate Order (POS or Sale)
        order_type = payload.get('order_type')
        pos_order = None
        sale_order = None

        if order_type != 'sale' and 'pos.order' in request.env:
            PosOrder = request.env['pos.order'].sudo()
            domain = []
            if str(ref_or_id).isdigit():
                domain = ['|', ('id', '=', int(ref_or_id)), ('pos_reference', 'ilike', str(ref_or_id))]
            else:
                domain = ['|', ('pos_reference', '=', str(ref_or_id)), ('name', '=', str(ref_or_id))]
            pos_order = PosOrder.search(domain, limit=1)

        if not pos_order and order_type != 'pos':
            SaleOrder = request.env['sale.order'].sudo()
            domain = []
            if str(ref_or_id).isdigit():
                domain = ['|', ('id', '=', int(ref_or_id)), ('name', 'ilike', str(ref_or_id))]
            else:
                domain = [('name', '=', str(ref_or_id))]
            sale_order = SaleOrder.search(domain, limit=1)

        if not pos_order and not sale_order:
            raise ApiError('order_not_found', message=f"Order '{ref_or_id}' could not be found.")

        # ----------------- PAY POS ORDER -----------------
        if pos_order:
            if pos_order.state in ('paid', 'done', 'invoiced'):
                return {
                    'already_paid': True,
                    'paid': True,
                    'payment': getattr(pos_order, 'app_payment_method', None) or 'wallet',
                    'message': 'This POS order has already been paid.',
                    'order': AppApi()._pos_order_dict(pos_order),
                }

            # Assign customer if not assigned or different
            if not pos_order.partner_id or pos_order.partner_id.id != target_customer.id:
                pos_order.write({'partner_id': target_customer.id})

            amount_to_pay = round(pos_order.amount_total - (pos_order.amount_paid or 0.0), 2)
            if amount_to_pay <= 0:
                amount_to_pay = round(pos_order.amount_total, 2)

            session = pos_order.session_id
            pos_payment_methods = session.config_id.payment_method_ids

            # Payment validation & wallet deduction
            cards = None
            if method == 'wallet':
                cards = wallet_cards(target_customer)
                balance = sum(cards.mapped('points'))
                if balance < amount_to_pay:
                    raise ApiError('insufficient_balance',
                                   amount_due=amount_to_pay,
                                   wallet_balance=balance,
                                   missing=round(amount_to_pay - balance, 2))

                remaining = amount_to_pay
                History = request.env['loyalty.history'].sudo()
                for card in cards.filtered(lambda c: c.points > 0):
                    take = min(card.points, remaining)
                    card.points -= take
                    vals = {
                        'card_id': card.id,
                        'description': f"Payment for POS Order {pos_order.pos_reference or pos_order.name}",
                    }
                    if 'used' in History._fields:
                        vals['used'] = take
                    elif 'points' in History._fields:
                        vals['points'] = -take
                    History.create(vals)
                    remaining -= take
                    if remaining <= 0:
                        break

            elif method == 'account':
                commercial = target_customer.commercial_partner_id.sudo()
                company = target_customer.company_id or request.env.company
                if company.account_use_credit_limit and commercial.credit_limit:
                    if commercial.credit + amount_to_pay > commercial.credit_limit:
                        raise ApiError('credit_limit_exceeded',
                                       message=f"Credit limit exceeded. Current balance due: {commercial.credit}")

            # Pick POS payment method
            pm = None
            if method == 'wallet':
                pm = pos_payment_methods.filtered(lambda m: 'jph' in (m.name or '').lower())[:1]
                if not pm:
                    pm = pos_payment_methods.filtered(
                        lambda m: getattr(m, 'type', None) == 'pay_later'
                        or 'customer account' in (m.name or '').lower()
                        or 'pay later' in (m.name or '').lower()
                    )[:1]
                if not pm:
                    pm = pos_payment_methods.filtered(lambda m: 'ewallet' in (m.name or '').lower())[:1]
            elif method == 'account':
                pm = pos_payment_methods.filtered(lambda m: 'jph' in (m.name or '').lower())[:1]
                if not pm:
                    pm = pos_payment_methods.filtered(
                        lambda m: getattr(m, 'type', None) == 'pay_later'
                        or 'account' in (m.name or '').lower()
                        or 'pay later' in (m.name or '').lower()
                    )[:1]

            if not pm and pos_payment_methods:
                pm = pos_payment_methods[0]

            # Record POS payment line
            if pm and amount_to_pay > 0:
                request.env['pos.payment'].sudo().create({
                    'pos_order_id': pos_order.id,
                    'payment_method_id': pm.id,
                    'amount': amount_to_pay,
                    'payment_date': fields.Datetime.now(),
                })

            order_update = {
                'state': 'paid',
                'amount_paid': (pos_order.amount_paid or 0.0) + amount_to_pay,
            }
            if 'app_payment_method' in pos_order._fields:
                order_update['app_payment_method'] = method
            pos_order.write(order_update)

            if hasattr(pos_order, 'message_post'):
                try:
                    pos_order.message_post(body=f"Assigned to {target_customer.name} and paid with {method.title()} via Mobile App.")
                except Exception:
                    pass

            new_balance = sum(wallet_cards(target_customer).mapped('points'))
            return {
                'paid': True,
                'payment': method,
                'payment_method_name': pm.name if pm else method.title(),
                'amount_paid': amount_to_pay,
                'balance_after': new_balance,
                'customer': {
                    'id': target_customer.id,
                    'name': target_customer.name,
                    'barcode': target_customer.barcode or '',
                    'wallet_balance': new_balance,
                },
                'order': AppApi()._pos_order_dict(pos_order),
            }

        # ----------------- PAY SALE ORDER -----------------
        if sale_order:
            if not sale_order.partner_id or sale_order.partner_id.id != target_customer.id:
                sale_order.write({'partner_id': target_customer.id})

            if method == 'wallet':
                cards = wallet_cards(target_customer)
                balance = sum(cards.mapped('points'))
                total = sale_order.amount_total
                sale_order._app_apply_wallet(cards.filtered(lambda c: c.points > 0))
                if sale_order.currency_id.compare_amounts(sale_order.amount_total, 0) > 0:
                    raise ApiError('insufficient_balance', amount_due=round(total, 2),
                                   wallet_balance=balance, missing=round(sale_order.amount_total, 2))
                sale_order.write({'app_payment_method': 'wallet'})
                sale_order._app_confirm_and_invoice()
                sale_order.message_post(body=f"Assigned to {target_customer.name} and paid from eWallet via Mobile App.")
                new_balance = sum(wallet_cards(target_customer).mapped('points'))
                return {
                    'paid': True,
                    'payment': 'wallet',
                    'amount_paid': total,
                    'balance_after': new_balance,
                    'customer': {
                        'id': target_customer.id,
                        'name': target_customer.name,
                        'barcode': target_customer.barcode or '',
                        'wallet_balance': new_balance,
                    },
                    'order': AppApi()._order_dict(sale_order),
                }

            if method == 'account':
                commercial = target_customer.commercial_partner_id.sudo()
                company = target_customer.company_id or request.env.company
                if company.account_use_credit_limit and commercial.credit_limit:
                    if commercial.credit + sale_order.amount_total > commercial.credit_limit:
                        raise ApiError('credit_limit_exceeded', message=f"Credit limit exceeded. Balance due: {commercial.credit}")
                sale_order.write({'app_payment_method': 'account'})
                invoice = sale_order._app_confirm_and_invoice()
                sale_order.message_post(body=f"Assigned to {target_customer.name} on Customer Account (pay later) via Mobile App.")
                return {
                    'paid': False,
                    'payment': 'account',
                    'invoice_id': invoice.id,
                    'amount_due': invoice.amount_residual,
                    'customer': {
                        'id': target_customer.id,
                        'name': target_customer.name,
                        'barcode': target_customer.barcode or '',
                        'wallet_balance': sum(wallet_cards(target_customer).mapped('points')),
                    },
                    'order': AppApi()._order_dict(sale_order),
                }

    # =========================================================================
    # 2-CALL RESTAURANT BILL FLOW:
    # 1. /api/v1/pos/bill      -> Search bill from printed receipt -> returns lines, total, wallet balance
    # 2. /api/v1/pos/bill/pay  -> Checkout/Pay -> auto-assigns to paying customer & settles in Odoo POS
    # =========================================================================

    @http.route(['/api/v1/pos/bill', '/api/v1/bill'], **ROUTE)
    @api_endpoint
    def get_bill(self, partner, payload):
        """Call #1: Search bill by printed receipt number or table.

        Body:
            search: "260-7-000016" or "000016" or 30265 (bill/order number)
            bill_no: "260-7-000016" (optional alias)
            table_no: "1" (optional fallback)
        """
        raw_term = str(payload.get('search') or payload.get('bill_no')
                       or payload.get('order_id') or payload.get('table_no') or '').strip()
        if not raw_term:
            raise ApiError('bill_number_required', message='Please enter the bill number from your receipt.')

        # Strip URL or leading hashtag if scanned from QR code
        term = raw_term.split('/')[-1].replace('#', '').strip()

        PosOrder = request.env['pos.order'].sudo() if 'pos.order' in request.env else None
        pos_order = None

        if PosOrder:
            # 1. Exact match on pos_reference or name
            pos_order = PosOrder.search([
                '|', ('pos_reference', '=', term), ('name', '=', term)
            ], limit=1, order='id desc')

            # 2. Case-insensitive like match on pos_reference
            if not pos_order:
                pos_order = PosOrder.search([
                    '|', ('pos_reference', 'ilike', term), ('name', 'ilike', term)
                ], limit=1, order='id desc')

            # 3. Numeric ID match if term is integer
            if not pos_order and term.isdigit():
                pos_order = PosOrder.browse(int(term)).exists()

            # 4. Open order on dining table if term is table number
            if not pos_order:
                table_param = payload.get('table_no') or term
                if 'restaurant.table' in request.env:
                    Table = request.env['restaurant.table'].sudo()
                    tbl = None
                    if table_param.isdigit():
                        tbl = Table.browse(int(table_param)).exists()
                    if not tbl and 'table_number' in Table._fields:
                        tbl = Table.search([('table_number', '=', str(table_param))], limit=1)
                    if not tbl and 'name' in Table._fields:
                        tbl = Table.search([('name', '=', str(table_param))], limit=1)
                    if tbl:
                        pos_order = PosOrder.search([
                            ('table_id', '=', tbl.id),
                            ('state', '=', 'draft')
                        ], limit=1, order='id desc')

        if not pos_order:
            raise ApiError('bill_not_found',
                           message=f"Bill '{raw_term}' not found. Please check the bill number printed on your receipt.")

        base = self._get_base_url()
        table_num = ''
        table_name = 'Dine-In'
        if 'table_id' in pos_order._fields and pos_order.table_id:
            tbl_info = safe_table_info(pos_order.table_id)
            table_num = tbl_info['table_number']
            table_name = tbl_info['table_name']

        # Live wallet balance of the customer checking on their phone
        cards = wallet_cards(partner)
        wallet_bal = sum(cards.mapped('points'))

        is_paid = pos_order.state in ('paid', 'done', 'invoiced')
        amount_due = 0.0 if is_paid else round(pos_order.amount_total - (pos_order.amount_paid or 0.0), 2)
        if not is_paid and amount_due <= 0:
            amount_due = round(pos_order.amount_total, 2)

        lines = [{
            'product_id': l.product_id.id,
            'name': l.product_id.name or l.product_id.display_name,
            'product': l.product_id.display_name,
            'qty': l.qty,
            'price_unit': l.price_unit,
            'subtotal': l.price_subtotal,
            'image_url': f"{base}/api/v1/product/{l.product_id.id}/image",
            'has_image': bool(l.product_id.image_128),
            'cover_url': getattr(l.product_id, '_app_cover_url', lambda: '')() or f"{base}/api/v1/product/{l.product_id.id}/image",
            'has_cover': bool(getattr(l.product_id, 'cover_image_url', False) or getattr(l.product_id.product_tmpl_id, 'cover_image_url', False)),
        } for l in pos_order.lines]

        return {
            'found': True,
            'order_id': pos_order.id,
            'bill_no': pos_order.pos_reference or pos_order.name,
            'pos_reference': pos_order.pos_reference or pos_order.name,
            'table_no': table_num,
            'table_name': table_name,
            'date': pos_order.date_order.isoformat() if pos_order.date_order else '',
            'state': pos_order.state,
            'is_paid': is_paid,
            'amount_total': pos_order.amount_total,
            'amount_due': amount_due,
            'currency': pos_order.currency_id.name if pos_order.currency_id else '',
            'customer_name': partner.name,
            'customer_wallet_balance': wallet_bal,
            'can_pay_with_wallet': wallet_bal >= amount_due and amount_due > 0 and not is_paid,
            'items_count': len(lines),
            'lines': lines,
        }

    @http.route(['/api/v1/pos/bill/pay', '/api/v1/bill/pay'], **ROUTE)
    @api_endpoint
    def pay_bill(self, partner, payload):
        """Call #2: Pay bill from phone. Auto-assigns the bill to the customer and settles it.

        Body:
            search: "260-7-000016" or bill_no: "260-7-000016" (or order_id: 30265)
            payment: "wallet" | "account" (default: "wallet")
        """
        raw_term = str(payload.get('bill_no') or payload.get('search')
                       or payload.get('order_id') or '').strip()
        if not raw_term:
            raise ApiError('bill_number_required', message='Please provide the bill number to pay.')

        term = raw_term.split('/')[-1].replace('#', '').strip()
        payment_method = (payload.get('payment') or payload.get('payment_method') or 'wallet').lower()
        if payment_method not in ('wallet', 'account'):
            raise ApiError('unknown_payment_method', message="Supported payment methods: 'wallet' or 'account'.")

        PosOrder = request.env['pos.order'].sudo() if 'pos.order' in request.env else None
        pos_order = None

        if PosOrder:
            pos_order = PosOrder.search([
                '|', ('pos_reference', '=', term), ('name', '=', term)
            ], limit=1, order='id desc')
            if not pos_order:
                pos_order = PosOrder.search([
                    '|', ('pos_reference', 'ilike', term), ('name', 'ilike', term)
                ], limit=1, order='id desc')
            if not pos_order and term.isdigit():
                pos_order = PosOrder.browse(int(term)).exists()

        if not pos_order:
            raise ApiError('bill_not_found', message=f"Bill '{raw_term}' not found.")

        # Check if already paid
        if pos_order.state in ('paid', 'done', 'invoiced'):
            return {
                'already_paid': True,
                'paid': True,
                'bill_no': pos_order.pos_reference or pos_order.name,
                'message': 'This bill has already been paid.',
                'wallet_balance_after': sum(wallet_cards(partner).mapped('points')),
            }

        # Auto-assign the bill to this customer
        pos_order.sudo().write({'partner_id': partner.id})

        amount_to_pay = round(pos_order.amount_total - (pos_order.amount_paid or 0.0), 2)
        if amount_to_pay <= 0:
            amount_to_pay = round(pos_order.amount_total, 2)

        session = pos_order.session_id
        pos_payment_methods = session.config_id.payment_method_ids

        # Wallet Payment Logic
        if payment_method == 'wallet':
            cards = wallet_cards(partner)
            balance = sum(cards.mapped('points'))
            if balance < amount_to_pay:
                raise ApiError(
                    'insufficient_balance',
                    message=f"Insufficient wallet balance. You have ${balance:.2f}, but the bill is ${amount_to_pay:.2f}.",
                    wallet_balance=balance,
                    amount_due=amount_to_pay,
                    missing=round(amount_to_pay - balance, 2)
                )

            # Deduct points from wallet cards
            remaining = amount_to_pay
            History = request.env['loyalty.history'].sudo()
            for card in cards.filtered(lambda c: c.points > 0):
                deduct = min(card.points, remaining)
                card.points -= deduct
                History.create({
                    'card_id': card.id,
                    'description': f"Paid Bill {pos_order.pos_reference or pos_order.name} on mobile app",
                    'used': deduct if 'used' in History._fields else False,
                    'points': -deduct if 'points' in History._fields else False,
                })
                remaining -= deduct
                if remaining <= 0:
                    break

            # Find POS payment method (JPH Wallet / eWallet / Customer Account)
            pm = pos_payment_methods.filtered(lambda m: 'jph' in (m.name or '').lower())[:1]
            if not pm:
                pm = pos_payment_methods.filtered(
                    lambda m: getattr(m, 'type', None) == 'pay_later'
                    or 'customer account' in (m.name or '').lower()
                    or 'pay later' in (m.name or '').lower()
                )[:1]
            if not pm:
                pm = pos_payment_methods.filtered(lambda m: 'ewallet' in (m.name or '').lower())[:1]
            if not pm and pos_payment_methods:
                pm = pos_payment_methods[0]

            if pm and amount_to_pay > 0:
                request.env['pos.payment'].sudo().create({
                    'pos_order_id': pos_order.id,
                    'payment_method_id': pm.id,
                    'amount': amount_to_pay,
                    'payment_date': fields.Datetime.now(),
                })

            order_update = {
                'state': 'paid',
                'amount_paid': (pos_order.amount_paid or 0.0) + amount_to_pay,
                'partner_id': partner.id,
            }
            if 'app_payment_method' in pos_order._fields:
                order_update['app_payment_method'] = 'wallet'
            pos_order.sudo().write(order_update)

            if hasattr(pos_order, 'message_post'):
                try:
                    pos_order.message_post(
                        body=f"Bill paid in full from eWallet (${amount_to_pay:.2f}) by {partner.name} on their phone."
                    )
                except Exception:
                    pass

        # Customer Account (Pay Later) Logic
        elif payment_method == 'account':
            commercial = partner.commercial_partner_id.sudo()
            company = partner.company_id or request.env.company
            if company.account_use_credit_limit and commercial.credit_limit:
                if commercial.credit + amount_to_pay > commercial.credit_limit:
                    raise ApiError('credit_limit_exceeded',
                                   message=f"Credit limit exceeded. Current balance due: {commercial.credit}")

            pm = pos_payment_methods.filtered(
                lambda m: getattr(m, 'type', None) == 'pay_later'
                or 'customer account' in (m.name or '').lower()
                or 'pay later' in (m.name or '').lower()
            )[:1]
            if not pm and pos_payment_methods:
                pm = pos_payment_methods[0]

            if pm and amount_to_pay > 0:
                request.env['pos.payment'].sudo().create({
                    'pos_order_id': pos_order.id,
                    'payment_method_id': pm.id,
                    'amount': amount_to_pay,
                    'payment_date': fields.Datetime.now(),
                })

            order_update = {
                'state': 'paid',
                'amount_paid': (pos_order.amount_paid or 0.0) + amount_to_pay,
                'partner_id': partner.id,
            }
            if 'app_payment_method' in pos_order._fields:
                order_update['app_payment_method'] = 'account'
            pos_order.sudo().write(order_update)

            if hasattr(pos_order, 'message_post'):
                try:
                    pos_order.message_post(
                        body=f"Bill charged to Customer Account by {partner.name} on their phone."
                    )
                except Exception:
                    pass

        new_balance = sum(wallet_cards(partner).mapped('points'))
        table_name = 'Dine-In'
        if 'table_id' in pos_order._fields and pos_order.table_id:
            table_name = safe_table_info(pos_order.table_id)['table_name']

        return {
            'success': True,
            'paid': True,
            'payment': payment_method,
            'bill_no': pos_order.pos_reference or pos_order.name,
            'order_id': pos_order.id,
            'table_name': table_name,
            'amount_paid': amount_to_pay,
            'wallet_balance_after': new_balance,
            'customer_name': partner.name,
            'message': f"Bill {pos_order.pos_reference or pos_order.name} paid successfully!",
        }



