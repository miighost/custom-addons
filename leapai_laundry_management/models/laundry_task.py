from odoo import models, fields


class LaundryTask(models.Model):
    _name = 'laundry.task'
    _description = 'Laundry Task'
    _inherit = ['mail.thread']
    _order = 'create_date desc'

    name = fields.Char(string='Task', required=True, tracking=True)
    order_id = fields.Many2one('laundry.order', string='Laundry Order', ondelete='cascade')
    order_line_id = fields.Many2one('laundry.order.line', string='Order Line', ondelete='set null')
    customer_id = fields.Many2one(related='order_id.customer_id', string='Customer', store=True)
    assigned_to = fields.Many2one('hr.employee', string='Assigned To', tracking=True)
    state = fields.Selection([
        ('new', 'New'),
        ('in_process', 'In Process'),
        ('done', 'Done'),
    ], string='Status', default='new', tracking=True)
    description = fields.Text(string='Description')
    spent_hours = fields.Float(string='Time Spent (hrs)')
    progress = fields.Integer(string='Progress %', default=0)
    date_start = fields.Datetime(string='Start Date')
    date_end = fields.Datetime(string='End Date')
    notes = fields.Text(string='Notes')

    def action_start(self):
        self.state = 'in_process'
        self.date_start = fields.Datetime.now()
        self.progress = 10

    def action_done(self):
        self.state = 'done'
        self.date_end = fields.Datetime.now()
        self.progress = 100
        if self.date_start and self.date_end:
            delta = self.date_end - self.date_start
            self.spent_hours = round(delta.total_seconds() / 3600, 2)

    def action_reset(self):
        self.state = 'new'
        self.progress = 0
