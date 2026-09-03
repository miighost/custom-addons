from odoo import api, fields, models


class AppDashboard(models.TransientModel):
    _name = 'app.dashboard'
    _description = 'Mobile App Dashboard'

    currency_id = fields.Many2one(
        'res.currency', compute='_compute_stats')

    # today
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
    due_total = fields.Monetary(compute='_compute_stats',
                                currency_field='currency_id')
    due_count = fields.Integer(compute='_compute_stats')

    # customers
    customers_total = fields.Integer(compute='_compute_stats')
    customers_week = fields.Integer(compute='_compute_stats')

    @api.depends_context('uid', 'allowed_company_ids')
    def _compute_stats(self):
        today = fields.Date.context_today(self)
        week_ago = fields.Date.subtract(today, days=7)
        day_start = fields.Datetime.to_datetime(today)

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
        cards = Card.search([('program_type', '=', 'ewallet')])
        open_invoices = Move.search([
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted'),
            ('payment_state', '!=', 'paid'),
            ('partner_id.firebase_uid', '!=', False),
        ])
        overdue = open_invoices.filtered(
            lambda m: m.invoice_date_due and m.invoice_date_due < today)

        for record in self:
            record.currency_id = self.env.company.currency_id
            record.orders_today = len(confirmed_today)
            record.revenue_today = sum(confirmed_today.mapped('amount_total'))
            record.orders_week = Order.search_count(app_orders + [
                ('date_order', '>=', fields.Datetime.to_datetime(week_ago)),
            ])
            record.quotations_pending = len(quotations)
            record.quotations_value = sum(quotations.mapped('amount_total'))
            record.wallet_total = sum(cards.mapped('points'))
            record.wallet_count = len(cards)
            record.due_total = sum(open_invoices.mapped('amount_residual'))
            record.due_count = len(open_invoices)
            record.overdue_total = sum(overdue.mapped('amount_residual'))
            record.overdue_count = len(overdue)
            record.customers_total = Partner.search_count(
                [('firebase_uid', '!=', False)])
            record.customers_week = Partner.search_count([
                ('firebase_uid', '!=', False),
                ('app_signup_date', '>=', fields.Datetime.to_datetime(week_ago)),
            ])

    # ------------------------------------------------------------ actions
    def _open(self, xmlid, domain=None, context=None):
        action = self.env['ir.actions.act_window']._for_xml_id(
            'odoo_app_api.%s' % xmlid)
        if domain is not None:
            action['domain'] = domain
        action['context'] = context or {}
        return action

    def action_open_orders(self):
        return self._open('action_app_orders',
                          domain=[('is_app_order', '=', True)])

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

    def action_open_customers(self):
        return self._open('action_app_customers')
