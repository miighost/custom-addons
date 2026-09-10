from odoo import models, api
from datetime import date


class LaundryDashboard(models.AbstractModel):
    _name = 'laundry.dashboard'
    _description = 'Laundry Dashboard'

    @api.model
    def get_dashboard_data(self):
        Order = self.env['laundry.order']
        Task = self.env['laundry.task']

        today = date.today()
        month_start = today.replace(day=1)

        total_orders = Order.search_count([])
        orders_draft = Order.search_count([('state', '=', 'draft')])
        orders_collected = Order.search_count([('state', '=', 'collected')])
        orders_in_process = Order.search_count([('state', '=', 'in_process')])
        orders_ready = Order.search_count([('state', '=', 'ready')])
        orders_picked_up = Order.search_count([('state', '=', 'picked_up')])
        orders_done = Order.search_count([('state', '=', 'done')])
        orders_this_month = Order.search_count([
            ('date', '>=', f'{month_start.strftime("%Y-%m-%d")} 00:00:00')
        ])

        tasks_new = Task.search_count([('state', '=', 'new')])
        tasks_in_process = Task.search_count([('state', '=', 'in_process')])
        tasks_done = Task.search_count([('state', '=', 'done')])

        # Revenue this month
        done_orders = Order.search([
            ('state', 'in', ['picked_up', 'done']),
            ('date', '>=', f'{month_start.strftime("%Y-%m-%d")} 00:00:00')
        ])
        revenue_this_month = sum(done_orders.mapped('total_amount'))

        # Delivery vs Pickup breakdown
        pickup_count = Order.search_count([('order_type', '=', 'pickup'), ('state', 'not in', ['cancel'])])
        delivery_count = Order.search_count([('order_type', '=', 'delivery'), ('state', 'not in', ['cancel'])])

        # Recent orders
        recent_orders = []
        for o in Order.search([], order='date desc', limit=10):
            recent_orders.append({
                'id': o.id,
                'name': o.name,
                'customer': o.customer_id.name or '',
                'date': o.date.strftime('%Y-%m-%d') if o.date else '',
                'order_type': o.order_type,
                'total': o.total_amount,
                'items': o.line_count,
                'currency_symbol': o.currency_id.symbol or '$',
                'state': o.state,
            })

        # Recent tasks
        recent_tasks = []
        for t in Task.search([], order='create_date desc', limit=8):
            recent_tasks.append({
                'id': t.id,
                'name': t.name,
                'customer': t.customer_id.name or '',
                'assigned': t.assigned_to.name or 'Unassigned',
                'progress': t.progress,
                'state': t.state,
                'order_name': t.order_id.name or '',
            })

        return {
            'total_orders': total_orders,
            'orders_draft': orders_draft,
            'orders_collected': orders_collected,
            'orders_in_process': orders_in_process,
            'orders_ready': orders_ready,
            'orders_picked_up': orders_picked_up,
            'orders_done': orders_done,
            'orders_this_month': orders_this_month,
            'tasks_new': tasks_new,
            'tasks_in_process': tasks_in_process,
            'tasks_done': tasks_done,
            'revenue_this_month': revenue_this_month,
            'pickup_count': pickup_count,
            'delivery_count': delivery_count,
            'recent_orders': recent_orders,
            'recent_tasks': recent_tasks,
            'currency_symbol': self.env.company.currency_id.symbol or '$',
        }
