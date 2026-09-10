from odoo import models, fields, api, _
from odoo.exceptions import UserError


class LaundryOrder(models.Model):
    _name = 'laundry.order'
    _description = 'Laundry Order'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'name'
    _order = 'date desc, id desc'

    name = fields.Char(string='Order Reference', required=True, copy=False,
        default='New', readonly=True)
    customer_id = fields.Many2one('res.partner', string='Customer', required=True, tracking=True)
    customer_ref = fields.Char(string='Customer Reference')
    order_type = fields.Selection([
        ('pickup', 'Pick Up'),
        ('delivery', 'Home Delivery'),
    ], string='Order Type', required=True, default='pickup', tracking=True)
    date = fields.Datetime(string='Order Date', required=True,
        default=fields.Datetime.now, tracking=True)
    deadline = fields.Date(string='Customer Deadline', tracking=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('collected', 'Collected'),
        ('in_process', 'In Process'),
        ('ready', 'Ready'),
        ('picked_up', 'Picked Up / Delivered'),
        ('done', 'Complete'),
        ('cancel', 'Cancelled'),
    ], string='Status', default='draft', tracking=True)

    cloth_line_ids = fields.One2many('laundry.order.line', 'order_id', string='Cloth Lines')
    task_ids = fields.One2many('laundry.task', 'order_id', string='Tasks')
    rating_id = fields.Many2one('laundry.rating', string='Rating', copy=False)
    invoice_ids = fields.Many2many('account.move', string='Invoices', copy=False)

    washing_charge = fields.Monetary(string='Washing Charge', compute='_compute_charges', store=True)
    extra_charge = fields.Monetary(string='Extra Service Charge', compute='_compute_charges', store=True)
    delivery_charge = fields.Monetary(string='Delivery Charge', default=0.0)
    total_amount = fields.Monetary(string='Total Amount', compute='_compute_total', store=True)

    notes = fields.Text(string='Internal Notes')
    terms = fields.Text(string='Terms & Conditions')
    staff_name = fields.Char(string='Staff Name')
    staff_phone = fields.Char(string='Staff Phone')
    picked_up_date = fields.Datetime(string='Picked Up / Delivered Date', readonly=True)

    task_count = fields.Integer(compute='_compute_task_count', string='Tasks')
    invoice_count = fields.Integer(compute='_compute_invoice_count', string='Invoices')
    line_count = fields.Integer(compute='_compute_line_count', string='Items')
    rating = fields.Selection([('good', 'Good'), ('average', 'Average'), ('bad', 'Bad')],
        related='rating_id.rating', string='Rating', store=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('laundry.order') or 'New'
        return super().create(vals_list)

    @api.depends('cloth_line_ids.washing_subtotal', 'cloth_line_ids.extra_subtotal')
    def _compute_charges(self):
        for order in self:
            order.washing_charge = sum(order.cloth_line_ids.mapped('washing_subtotal'))
            order.extra_charge = sum(order.cloth_line_ids.mapped('extra_subtotal'))

    @api.depends('washing_charge', 'extra_charge', 'delivery_charge')
    def _compute_total(self):
        for order in self:
            order.total_amount = order.washing_charge + order.extra_charge + order.delivery_charge

    def _compute_task_count(self):
        for order in self:
            order.task_count = len(order.task_ids)

    def _compute_invoice_count(self):
        for order in self:
            order.invoice_count = len(order.invoice_ids)

    def _compute_line_count(self):
        for order in self:
            order.line_count = len(order.cloth_line_ids)


    @api.depends('rating_id', 'rating_id.rating')
    def _compute_rating(self):
        for order in self:
            order.rating = order.rating_id.rating if order.rating_id else False

    # --- Workflow Actions ---

    def action_collect(self):
        self.state = 'collected'
        self.message_post(body=_('Clothes collected from customer.'))

    def action_start_process(self):
        self.state = 'in_process'
        self._create_tasks()
        self.message_post(body=_('Laundry processing started.'))

    def action_ready(self):
        self.state = 'ready'
        self.message_post(body=_('Laundry is ready for pickup/delivery.'))

    def action_pickup_delivery(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Pickup / Delivery'),
            'res_model': 'laundry.pickup.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_order_id': self.id, 'default_order_type': self.order_type},
        }

    def action_done(self):
        self.state = 'done'
        self.message_post(body=_('Order completed.'))

    def action_cancel(self):
        for order in self:
            if order.state in ('done',):
                raise UserError(_('Cannot cancel a completed order.'))
            order.state = 'cancel'
            order.message_post(body=_('Order cancelled.'))

    def action_reset_draft(self):
        self.state = 'draft'

    def _create_tasks(self):
        for line in self.cloth_line_ids:
            if not self.env['laundry.task'].search([('order_line_id', '=', line.id)]):
                self.env['laundry.task'].create({
                    'name': f'{line.cloth_type_id.name} - {line.service_id.name}',
                    'order_id': self.id,
                    'order_line_id': line.id,
                    'description': f'Cloth: {line.cloth_type_id.name}\nService: {line.service_id.name}\nQty: {line.qty}\nNotes: {line.notes or ""}',
                })

    def action_generate_invoice(self):
        self.ensure_one()
        if not self.cloth_line_ids:
            raise UserError(_('Add cloth lines before generating invoice.'))
        invoice_lines = []
        for line in self.cloth_line_ids:
            if line.service_id and line.service_id.product_id:
                invoice_lines.append((0, 0, {
                    'product_id': line.service_id.product_id.id,
                    'name': f'{line.cloth_type_id.name} - {line.service_id.name}',
                    'quantity': line.qty,
                    'price_unit': line.washing_price,
                }))
            else:
                invoice_lines.append((0, 0, {
                    'name': f'{line.cloth_type_id.name} - {line.service_id.name}',
                    'quantity': line.qty,
                    'price_unit': line.washing_price,
                }))
        if self.delivery_charge:
            invoice_lines.append((0, 0, {
                'name': _('Delivery Charge'),
                'quantity': 1,
                'price_unit': self.delivery_charge,
            }))
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.customer_id.id,
            'invoice_date': fields.Date.today(),
            'ref': self.name,
            'invoice_line_ids': invoice_lines,
        })
        self.invoice_ids = [(4, invoice.id)]
        return {
            'type': 'ir.actions.act_window',
            'name': _('Invoice'),
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': invoice.id,
        }

    def action_view_tasks(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Laundry Tasks'),
            'res_model': 'laundry.task',
            'view_mode': 'list,form,kanban',
            'domain': [('order_id', '=', self.id)],
            'context': {'default_order_id': self.id},
        }

    def action_view_invoices(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Invoices'),
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.invoice_ids.ids)],
        }
