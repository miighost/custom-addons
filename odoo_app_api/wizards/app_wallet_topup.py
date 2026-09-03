from odoo import _, api, fields, models
from odoo.exceptions import UserError


class AppWalletTopup(models.TransientModel):
    _name = 'app.wallet.topup'
    _description = 'Top Up a JPH Wallet'

    partner_id = fields.Many2one(
        'res.partner', string='Customer', required=True,
        domain="[('is_company', 'in', (True, False))]")
    program_id = fields.Many2one(
        'loyalty.program', string='Wallet Program', required=True,
        domain="[('program_type', '=', 'ewallet'), ('active', '=', True)]",
        default=lambda self: self._default_program())
    product_id = fields.Many2one(
        'product.product', string='Top-Up Product', required=True,
        help="The service product the top-up is sold as. Its price is "
             "overridden by the amount below.")
    available_product_ids = fields.Many2many(
        'product.product', compute='_compute_available_products')

    amount = fields.Monetary(string='Amount', required=True,
                             currency_field='currency_id')
    currency_id = fields.Many2one('res.currency',
                                  related='program_id.currency_id')
    current_balance = fields.Monetary(compute='_compute_current_balance',
                                      currency_field='currency_id',
                                      string='Current Balance')

    register_payment = fields.Boolean(
        string='Customer is paying now', default=True,
        help="Invoices the top-up and registers the payment immediately. "
             "Untick to leave an unpaid invoice for the customer to settle "
             "later - the balance is credited either way.")
    journal_id = fields.Many2one(
        'account.journal', string='Paid Into',
        domain="[('type', 'in', ('bank', 'cash'))]",
        default=lambda self: self._default_journal())
    memo = fields.Char(string='Reference',
                       help="Shown on the wallet statement line.")

    # ------------------------------------------------------------ defaults
    @api.model
    def _default_program(self):
        return self.env['loyalty.program'].search(
            [('program_type', '=', 'ewallet'), ('active', '=', True)], limit=1)

    @api.model
    def _default_journal(self):
        param = self.env['ir.config_parameter'].sudo().get_param(
            'app_api.wallet_journal_id')
        if param:
            journal = self.env['account.journal'].browse(int(param)).exists()
            if journal:
                return journal
        return self.env['account.journal'].search(
            [('type', 'in', ('bank', 'cash')),
             ('company_id', '=', self.env.company.id)], limit=1)

    # ------------------------------------------------------------ computes
    @api.depends('program_id')
    def _compute_available_products(self):
        for wizard in self:
            wizard.available_product_ids = wizard.program_id.trigger_product_ids

    @api.depends('partner_id', 'program_id')
    def _compute_current_balance(self):
        for wizard in self:
            cards = self.env['loyalty.card'].search([
                ('program_id', '=', wizard.program_id.id),
                ('partner_id', '=', wizard.partner_id.commercial_partner_id.id),
            ]) if wizard.partner_id and wizard.program_id else False
            wizard.current_balance = sum(cards.mapped('points')) if cards else 0.0

    @api.onchange('program_id')
    def _onchange_program_id(self):
        products = self.program_id.trigger_product_ids
        if self.product_id not in products:
            self.product_id = products[:1]

    # ------------------------------------------------------------- action
    def action_topup(self):
        self.ensure_one()
        if self.amount <= 0:
            raise UserError(_("Enter an amount greater than zero."))
        if self.product_id not in self.program_id.trigger_product_ids:
            raise UserError(_(
                "%(product)s is not one of the eWallet Products on the "
                "%(program)s program. Add it there first, or pick another "
                "product.",
                product=self.product_id.display_name,
                program=self.program_id.name))
        if self.register_payment and not self.journal_id:
            raise UserError(_("Choose the journal the money was paid into."))

        order = self.env['sale.order'].create({
            'partner_id': self.partner_id.id,
            'origin': self.memo or _('Wallet top-up'),
            'order_line': [(0, 0, {
                'product_id': self.product_id.id,
                'product_uom_qty': 1,
                'price_unit': self.amount,
                'name': self.memo or _('eWallet top-up'),
            })],
        })
        # Confirming the order is what credits the wallet - the loyalty
        # program awards points equal to the money spent on its trigger
        # product, which is why the line price carries the amount.
        order.action_confirm()

        if self.register_payment:
            invoice = order._create_invoices()
            invoice.action_post()
            self.env['account.payment.register'].with_context(
                active_model='account.move', active_ids=invoice.ids,
            ).create({
                'journal_id': self.journal_id.id,
                'amount': self.amount,
                'payment_date': fields.Date.context_today(self),
                'communication': self.memo or order.name,
            })._create_payments()

        order.message_post(body=_(
            "eWallet top-up of %(amount)s recorded from the back office.",
            amount=self.amount))

        return {
            'type': 'ir.actions.act_window',
            'name': _('Top-Up Order'),
            'res_model': 'sale.order',
            'res_id': order.id,
            'view_mode': 'form',
            'target': 'current',
        }
