from datetime import datetime, time

import pytz

from odoo import _, api, fields, models


class AppDashboard(models.Model):
    """The Mobile App landing screen.

    One record (`app_dashboard_main`) whose figures are computed live each
    time it is read; nothing is stored on it. The menu opens that record
    read-only. Opening the form without a record would show an unsaved new
    record instead - Save / Discard buttons and a technical breadcrumb.
    """
    _name = 'app.dashboard'
    _description = 'Mobile App Dashboard'

    currency_id = fields.Many2one(
        'res.currency', compute='_compute_stats')

    # POS / Restaurant Orders
    pos_orders_today = fields.Integer(compute='_compute_stats')
    pos_revenue_today = fields.Monetary(compute='_compute_stats',
                                        currency_field='currency_id')
    pos_orders_week = fields.Integer(compute='_compute_stats')

    # Sale Orders
    orders_today = fields.Integer(compute='_compute_stats')
    revenue_today = fields.Monetary(compute='_compute_stats',
                                    currency_field='currency_id')
    orders_week = fields.Integer(compute='_compute_stats')

    # needs attention
    quotations_pending = fields.Integer(compute='_compute_stats')
    quotations_value = fields.Monetary(compute='_compute_stats',
                                       currency_field='currency_id')
    overdue_total = fields.Monetary(compute='_compute_stats',
                                    currency_field='currency_id')
    overdue_count = fields.Integer(compute='_compute_stats')

    # money
    wallet_total = fields.Monetary(compute='_compute_stats',
                                   currency_field='currency_id')
    wallet_count = fields.Integer(compute='_compute_stats')
    wallet_spent_today = fields.Monetary(compute='_compute_stats',
                                         currency_field='currency_id',
                                         string='eWallet Spent Today')
    wallet_spent_count = fields.Integer(compute='_compute_stats',
                                        string='eWallet Payments Today')
    due_total = fields.Monetary(compute='_compute_stats',
                                currency_field='currency_id')
    due_count = fields.Integer(compute='_compute_stats')

    # customers
    customers_total = fields.Integer(compute='_compute_stats')
    customers_week = fields.Integer(compute='_compute_stats')

    recent_order_ids = fields.Many2many('sale.order', compute='_compute_stats',
                                        string='Latest App Sale Orders')
    recent_pos_order_ids = fields.Many2many('pos.order', compute='_compute_stats',
                                            string='Latest POS Orders')
    pos_orders_grouped_html = fields.Html(
        compute='_compute_stats', sanitize=False, string='POS Orders Grouped')
    sale_orders_grouped_html = fields.Html(
        compute='_compute_stats', sanitize=False, string='Sale Orders Grouped')

    date_filter = fields.Selection([
        ('today', 'Today'),
        ('week', 'This Week'),
        ('month', 'This Month'),
        ('all', 'All Time'),
    ], compute='_compute_filter_state', string='Filter Period')
    is_expanded = fields.Boolean(compute='_compute_filter_state', string='Expand All Groups')

    @api.depends_context('dashboard_date_filter', 'dashboard_is_expanded')
    def _compute_filter_state(self):
        df = self.env.context.get('dashboard_date_filter') or 'today'
        is_exp = bool(self.env.context.get('dashboard_is_expanded'))
        for record in self:
            record.date_filter = df
            record.is_expanded = is_exp

    @api.depends_context('uid', 'allowed_company_ids', 'dashboard_date_filter', 'dashboard_is_expanded')
    def _compute_stats(self):
        today = fields.Date.context_today(self)
        week_ago = fields.Date.subtract(today, days=7)
        month_ago = today.replace(day=1)
        day_start = self._utc_start_of(today)
        week_start = self._utc_start_of(week_ago)
        month_start = self._utc_start_of(month_ago)

        Order = self.env['sale.order']
        Move = self.env['account.move']
        Card = self.env['loyalty.card']
        Partner = self.env['res.partner']

        app_orders = [('is_app_order', '=', True)]

        confirmed_today = Order.search(app_orders + [
            ('state', 'in', ('sale', 'done')),
            ('date_order', '>=', day_start),
        ])
        quotations = Order.search(app_orders + [
            ('state', 'in', ('draft', 'sent')),
        ])

        pos_orders_today = []
        pos_orders_week_count = 0
        PosOrder = self.env['pos.order'] if 'pos.order' in self.env else None
        pos_app_domain = [('session_id.config_id', '=', 7)]
        if PosOrder is not None:
            if 'is_app_order' in PosOrder._fields:
                pos_app_domain = ['|', ('is_app_order', '=', True), ('session_id.config_id', '=', 7)]
            pos_orders_today = PosOrder.search(pos_app_domain + [
                ('state', 'in', ('paid', 'done')),
                ('date_order', '>=', day_start),
            ])
            pos_orders_week_count = PosOrder.search_count(pos_app_domain + [
                ('state', 'in', ('paid', 'done')),
                ('date_order', '>=', week_start),
            ])

        cards = Card.search([('program_type', '=', 'ewallet')])
        open_invoices = Move.search([
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted'),
            ('payment_state', '!=', 'paid'),
            ('partner_id.firebase_uid', '!=', False),
        ])
        overdue = open_invoices.filtered(
            lambda m: m.invoice_date_due and m.invoice_date_due < today)

        # eWallet spend calculation for today
        wallet_spent = 0.0
        wallet_spent_count = 0
        if 'loyalty.history' in self.env:
            History = self.env['loyalty.history']
            h_domain = [
                ('card_id.program_type', '=', 'ewallet'),
                ('create_date', '>=', day_start),
            ]
            if 'used' in History._fields:
                spend_lines = History.search(h_domain + [('used', '>', 0)])
                wallet_spent = sum(spend_lines.mapped('used'))
                wallet_spent_count = len(spend_lines)
            elif 'points' in History._fields:
                spend_lines = History.search(h_domain + [('points', '<', 0)])
                wallet_spent = abs(sum(spend_lines.mapped('points')))
                wallet_spent_count = len(spend_lines)

        if wallet_spent == 0.0:
            if PosOrder is not None and 'app_payment_method' in PosOrder._fields:
                pos_wallet = PosOrder.search([
                    ('app_payment_method', '=', 'wallet'),
                    ('date_order', '>=', day_start),
                    ('state', 'in', ('paid', 'done')),
                ])
                wallet_spent += sum(pos_wallet.mapped('amount_total'))
                wallet_spent_count += len(pos_wallet)
            if 'app_payment_method' in Order._fields:
                sale_wallet = Order.search(app_orders + [
                    ('app_payment_method', '=', 'wallet'),
                    ('date_order', '>=', day_start),
                    ('state', 'in', ('sale', 'done')),
                ])
                wallet_spent += sum(sale_wallet.mapped('amount_total'))
                wallet_spent_count += len(sale_wallet)

        for record in self:
            # Determine start cutoff for orders based on selected period
            df = record.date_filter or 'today'
            if df == 'today':
                cutoff = day_start
            elif df == 'week':
                cutoff = week_start
            elif df == 'month':
                cutoff = month_start
            else:
                cutoff = False

            recent_pos = []
            if PosOrder is not None:
                pos_filter = list(pos_app_domain)
                if cutoff:
                    pos_filter.append(('date_order', '>=', cutoff))
                recent_pos = PosOrder.search(pos_filter, order='date_order desc, id desc', limit=100)

            sale_filter = list(app_orders)
            if cutoff:
                sale_filter.append(('date_order', '>=', cutoff))
            recent_orders = Order.search(sale_filter, order='date_order desc, id desc', limit=100)

            record.currency_id = self.env.company.currency_id
            record.pos_orders_today = len(pos_orders_today)
            record.pos_revenue_today = sum(pos_orders_today.mapped('amount_total'))
            record.pos_orders_week = pos_orders_week_count
            record.recent_pos_order_ids = recent_pos

            record.orders_today = len(confirmed_today)
            record.revenue_today = sum(confirmed_today.mapped('amount_total'))
            record.orders_week = Order.search_count(app_orders + [
                ('date_order', '>=', week_start),
            ])
            record.quotations_pending = len(quotations)
            record.quotations_value = sum(quotations.mapped('amount_total'))
            record.wallet_total = sum(cards.mapped('points'))
            record.wallet_count = len(cards)
            record.wallet_spent_today = wallet_spent
            record.wallet_spent_count = wallet_spent_count
            record.due_total = sum(open_invoices.mapped('amount_residual'))
            record.due_count = len(open_invoices)
            record.overdue_total = sum(overdue.mapped('amount_residual'))
            record.overdue_count = len(overdue)
            record.customers_total = Partner.search_count(
                [('firebase_uid', '!=', False)])
            record.customers_week = Partner.search_count([
                ('firebase_uid', '!=', False),
                ('app_signup_date', '>=', week_start),
            ])
            record.recent_order_ids = recent_orders
            record.pos_orders_grouped_html = self._build_pos_orders_html(
                recent_pos, record.currency_id, is_expanded=record.is_expanded)
            record.sale_orders_grouped_html = self._build_sale_orders_html(
                recent_orders, record.currency_id, is_expanded=record.is_expanded)

    def _format_money(self, amount, currency):
        symbol = currency.symbol or '$'
        val = f"{amount:,.2f}"
        if currency.position == 'after':
            return f"{val} {symbol}"
        return f"{symbol} {val}"

    def _format_date(self, dt):
        if not dt:
            return ''
        user_tz = pytz.timezone(self.env.context.get('tz') or self.env.user.tz or 'UTC')
        local_dt = pytz.utc.localize(dt).astimezone(user_tz)
        return local_dt.strftime('%b %d, %I:%M %p')

    def _build_pos_orders_html(self, orders, currency, is_expanded=False):
        if not orders:
            return '<p class="text-muted mt-2">No POS orders from the app for this period.</p>'

        grouped = {}
        for order in orders:
            partner = order.partner_id
            pid = partner.id if partner else 0
            pname = partner.name if partner else _("Walk-in / Guest")
            if pid not in grouped:
                grouped[pid] = {
                    'name': pname,
                    'orders': [],
                    'total': 0.0,
                }
            grouped[pid]['orders'].append(order)
            grouped[pid]['total'] += order.amount_total

        sorted_groups = sorted(
            grouped.values(),
            key=lambda g: g['orders'][0].date_order if (g['orders'] and g['orders'][0].date_order) else datetime.min,
            reverse=True
        )

        open_attr = 'open="open"' if is_expanded else ''
        html_blocks = []
        for g in sorted_groups:
            pname = g['name']
            order_count = len(g['orders'])
            total_formatted = self._format_money(g['total'], currency)
            orders_rows = []
            for o in g['orders']:
                ref = getattr(o, 'order_reference', False) or getattr(o, 'pos_reference', False) or o.name or ''
                ref_link = f'<a href="/web#id={o.id}&amp;model=pos.order&amp;view_type=form" target="_blank" class="fw-bold text-primary text-decoration-none" title="Open POS Order #{o.id}">{ref} <i class="fa fa-external-link text-muted ms-1" style="font-size: 11px;"></i></a>'
                date_str = self._format_date(o.date_order)
                tbl = getattr(o, 'table_label', '') or ''
                tbl_html = f'<span class="badge bg-light text-dark border">{tbl}</span>' if tbl else '<span class="text-muted">-</span>'
                pay = ''
                if hasattr(o, 'app_payment_method') and o.app_payment_method:
                    pay = dict(o._fields['app_payment_method'].selection).get(o.app_payment_method, o.app_payment_method)
                elif hasattr(o, 'payment_ids') and o.payment_ids:
                    pay = ", ".join(o.payment_ids.mapped('payment_method_id.name'))
                pay_str = str(pay or '')
                if (hasattr(o, 'app_payment_method') and o.app_payment_method == 'wallet') or 'wallet' in pay_str.lower():
                    pay_html = '<span class="badge" style="background-color: #FFF3CD; color: #856404; border: 1px solid #FFEBAA; font-weight: 600;"><i class="fa fa-credit-card me-1"></i>eWallet</span>'
                else:
                    pay_html = pay_str or '<span class="text-muted">-</span>'
                amt = self._format_money(o.amount_total, currency)
                state_val = o.state
                badge_bg = 'bg-success' if state_val in ('paid', 'done') else ('bg-info' if state_val == 'draft' else 'bg-secondary')
                state_label = dict(o._fields['state'].selection).get(state_val, state_val.capitalize()) if 'state' in o._fields else state_val

                orders_rows.append(f"""
                    <tr>
                        <td>{ref_link}</td>
                        <td class="text-muted">{date_str}</td>
                        <td>{tbl_html}</td>
                        <td>{pay_html}</td>
                        <td class="text-end fw-bold text-dark">{amt}</td>
                        <td class="text-center"><span class="badge rounded-pill {badge_bg} text-white px-2 py-1">{state_label}</span></td>
                    </tr>
                """)

            rows_html = "".join(orders_rows)
            count_label = f"{order_count} order" if order_count == 1 else f"{order_count} orders"
            html_blocks.append(f"""
                <details {open_attr} class="o_app_customer_group">
                    <summary class="d-flex justify-content-between align-items-center" style="cursor: pointer;">
                        <div class="d-flex align-items-center">
                            <i class="fa fa-chevron-right me-3 text-muted toggle-icon"></i>
                            <span class="fw-bold fs-6 text-dark me-2" style="font-size: 1rem; color: #212529 !important;"><i class="fa fa-user me-2 text-primary"></i>{pname}</span>
                            <span class="o_app_order_count_badge" style="background-color: #FFD83D !important; color: #111827 !important; padding: 3px 10px; border-radius: 12px; font-weight: 700; font-size: 12px; display: inline-block; vertical-align: middle; margin-left: 8px; line-height: 1.2; box-shadow: 0 1px 2px rgba(0,0,0,0.06);">{count_label}</span>
                        </div>
                        <div class="text-end">
                            <span class="text-muted small me-2">Total:</span>
                            <span class="fw-bold text-success fs-6" style="font-weight: 700;">{total_formatted}</span>
                        </div>
                    </summary>
                    <div class="table-responsive">
                        <table class="table table-sm table-hover align-middle mb-0">
                            <thead class="table-light text-muted small">
                                <tr>
                                    <th style="width: 25%;">Order Ref</th>
                                    <th style="width: 25%;">Date</th>
                                    <th style="width: 12%;">Table</th>
                                    <th style="width: 15%;">Paid With</th>
                                    <th class="text-end" style="width: 13%;">Total</th>
                                    <th class="text-center" style="width: 10%;">Status</th>
                                </tr>
                            </thead>
                            <tbody>
                                {rows_html}
                            </tbody>
                        </table>
                    </div>
                </details>
            """)

        return "".join(html_blocks)

    def _build_sale_orders_html(self, orders, currency, is_expanded=False):
        if not orders:
            return '<p class="text-muted mb-4 mt-2">No Sale orders from the app for this period.</p>'

        grouped = {}
        for order in orders:
            partner = order.partner_id
            pid = partner.id if partner else 0
            pname = partner.name if partner else _("App Customer")
            if pid not in grouped:
                grouped[pid] = {
                    'name': pname,
                    'orders': [],
                    'total': 0.0,
                }
            grouped[pid]['orders'].append(order)
            grouped[pid]['total'] += order.amount_total

        sorted_groups = sorted(
            grouped.values(),
            key=lambda g: g['orders'][0].date_order if (g['orders'] and g['orders'][0].date_order) else datetime.min,
            reverse=True
        )

        open_attr = 'open="open"' if is_expanded else ''
        html_blocks = []
        for g in sorted_groups:
            pname = g['name']
            order_count = len(g['orders'])
            total_formatted = self._format_money(g['total'], currency)
            orders_rows = []
            for o in g['orders']:
                name = o.name or ''
                name_link = f'<a href="/web#id={o.id}&amp;model=sale.order&amp;view_type=form" target="_blank" class="fw-bold text-primary text-decoration-none" title="Open Sale Order #{o.id}">{name} <i class="fa fa-external-link text-muted ms-1" style="font-size: 11px;"></i></a>'
                date_str = self._format_date(o.date_order)
                pay = ''
                if hasattr(o, 'app_payment_method') and o.app_payment_method:
                    pay = dict(o._fields['app_payment_method'].selection).get(o.app_payment_method, o.app_payment_method)
                pay_str = str(pay or '')
                if (hasattr(o, 'app_payment_method') and o.app_payment_method == 'wallet') or 'wallet' in pay_str.lower():
                    pay_html = '<span class="badge" style="background-color: #FFF3CD; color: #856404; border: 1px solid #FFEBAA; font-weight: 600;"><i class="fa fa-credit-card me-1"></i>eWallet</span>'
                else:
                    pay_html = pay_str or '<span class="text-muted">-</span>'
                amt = self._format_money(o.amount_total, currency)
                state_val = o.state
                badge_bg = 'bg-success' if state_val in ('sale', 'done') else ('bg-warning' if state_val in ('draft', 'sent') else 'bg-secondary')
                state_label = dict(o._fields['state'].selection).get(state_val, state_val.capitalize()) if 'state' in o._fields else state_val

                orders_rows.append(f"""
                    <tr>
                        <td>{name_link}</td>
                        <td class="text-muted">{date_str}</td>
                        <td>{pay_html}</td>
                        <td class="text-end fw-bold text-dark">{amt}</td>
                        <td class="text-center"><span class="badge rounded-pill {badge_bg} text-white px-2 py-1">{state_label}</span></td>
                    </tr>
                """)

            rows_html = "".join(orders_rows)
            count_label = f"{order_count} order" if order_count == 1 else f"{order_count} orders"
            html_blocks.append(f"""
                <details {open_attr} class="o_app_customer_group">
                    <summary class="d-flex justify-content-between align-items-center" style="cursor: pointer;">
                        <div class="d-flex align-items-center">
                            <i class="fa fa-chevron-right me-3 text-muted toggle-icon"></i>
                            <span class="fw-bold fs-6 text-dark me-2" style="font-size: 1rem; color: #212529 !important;"><i class="fa fa-user me-2 text-primary"></i>{pname}</span>
                            <span class="o_app_order_count_badge" style="background-color: #FFD83D !important; color: #111827 !important; padding: 3px 10px; border-radius: 12px; font-weight: 700; font-size: 12px; display: inline-block; vertical-align: middle; margin-left: 8px; line-height: 1.2; box-shadow: 0 1px 2px rgba(0,0,0,0.06);">{count_label}</span>
                        </div>
                        <div class="text-end">
                            <span class="text-muted small me-2">Total:</span>
                            <span class="fw-bold text-success fs-6" style="font-weight: 700;">{total_formatted}</span>
                        </div>
                    </summary>
                    <div class="table-responsive">
                        <table class="table table-sm table-hover align-middle mb-0">
                            <thead class="table-light text-muted small">
                                <tr>
                                    <th style="width: 30%;">Order</th>
                                    <th style="width: 30%;">Date</th>
                                    <th style="width: 20%;">Paid With</th>
                                    <th class="text-end" style="width: 10%;">Total</th>
                                    <th class="text-center" style="width: 10%;">Status</th>
                                </tr>
                            </thead>
                            <tbody>
                                {rows_html}
                            </tbody>
                        </table>
                    </div>
                </details>
            """)

        return "".join(html_blocks)

    def _action_open_dashboard(self, date_filter=None, is_expanded=None):
        ctx = dict(self.env.context)
        if date_filter is not None:
            ctx['dashboard_date_filter'] = date_filter
        if is_expanded is not None:
            ctx['dashboard_is_expanded'] = is_expanded
        main_rec = self.env.ref('odoo_app_api.app_dashboard_main', raise_if_not_found=False)
        main_id = main_rec.id if main_rec else (self.id or 1)
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'app.dashboard',
            'res_id': main_id,
            'view_mode': 'form',
            'target': 'current',
            'context': ctx,
        }

    def action_filter_today(self):
        return self._action_open_dashboard(date_filter='today')

    def action_filter_week(self):
        return self._action_open_dashboard(date_filter='week')

    def action_filter_month(self):
        return self._action_open_dashboard(date_filter='month')

    def action_filter_all(self):
        return self._action_open_dashboard(date_filter='all')

    def action_toggle_expand(self):
        current_exp = bool(self.env.context.get('dashboard_is_expanded'))
        return self._action_open_dashboard(is_expanded=not current_exp)

    def _compute_display_name(self):
        for record in self:
            record.display_name = _("Mobile App")

    def _utc_start_of(self, day):
        """Local midnight of `day`, as the naive UTC datetimes Odoo stores."""
        tz = pytz.timezone(self.env.context.get('tz') or self.env.user.tz or 'UTC')
        midnight = tz.localize(datetime.combine(day, time.min))
        return midnight.astimezone(pytz.utc).replace(tzinfo=None)

    # ------------------------------------------------------------ actions
    def _open(self, xmlid, domain=None, context=None):
        action = self.env['ir.actions.act_window']._for_xml_id(
            'odoo_app_api.%s' % xmlid)
        if domain is not None:
            action['domain'] = domain
        action['context'] = context or {}
        return action

    def action_open_pos_orders(self):
        """Open all app POS orders grouped by customer."""
        action = self._open('action_app_pos_orders')
        action['context'] = {'search_default_customer': 1}
        return action

    def action_open_pos_orders_today(self):
        """Open today's app POS orders."""
        day_start = self._utc_start_of(fields.Date.context_today(self))
        pos_domain = [
            '|', ('is_app_order', '=', True), ('session_id.config_id', '=', 7),
            ('date_order', '>=', day_start),
        ]
        return self._open('action_app_pos_orders', domain=pos_domain)

    def action_open_orders(self):
        """Open all app Sale orders grouped by customer."""
        action = self._open('action_app_orders',
                            domain=[('is_app_order', '=', True)])
        action['context'] = {'search_default_customer': 1}
        return action

    def action_open_orders_today(self):
        """The orders the "Sale Orders today" card counts."""
        day_start = self._utc_start_of(fields.Date.context_today(self))
        return self._open('action_app_orders', domain=[
            ('is_app_order', '=', True),
            ('state', 'in', ('sale', 'done')),
            ('date_order', '>=', day_start),
        ])

    def action_open_quotations(self):
        return self._open('action_app_orders', domain=[
            ('is_app_order', '=', True),
            ('state', 'in', ('draft', 'sent')),
        ])

    def action_open_invoices(self):
        return self._open('action_app_invoices', domain=[
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted'),
            ('payment_state', '!=', 'paid'),
            ('partner_id.firebase_uid', '!=', False),
        ])

    def action_open_overdue(self):
        return self._open('action_app_invoices', domain=[
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted'),
            ('payment_state', '!=', 'paid'),
            ('invoice_date_due', '<', fields.Date.context_today(self)),
            ('partner_id.firebase_uid', '!=', False),
        ])

    def action_open_wallets(self):
        return self._open('action_jph_wallets')

    def action_open_wallet_spent(self):
        """Open today's eWallet spend movements or POS orders paid with wallet."""
        day_start = self._utc_start_of(fields.Date.context_today(self))
        if 'loyalty.history' in self.env:
            action = self.env['ir.actions.act_window']._for_xml_id('odoo_app_api.action_wallet_history')
            domain = [
                ('card_id.program_type', '=', 'ewallet'),
                ('create_date', '>=', day_start),
            ]
            History = self.env['loyalty.history']
            if 'used' in History._fields:
                domain.append(('used', '>', 0))
            elif 'points' in History._fields:
                domain.append(('points', '<', 0))
            action['domain'] = domain
            action['name'] = _("Today's eWallet Spent")
            return action
        elif 'pos.order' in self.env:
            action = self._open('action_app_pos_orders')
            action['domain'] = [
                ('app_payment_method', '=', 'wallet'),
                ('date_order', '>=', day_start),
            ]
            action['name'] = _("Today's eWallet Orders")
            return action
        return self._open('action_wallet_history')

    def action_open_customers(self):
        return self._open('action_app_customers')
