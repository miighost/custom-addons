# -*- coding: utf-8 -*-
#############################################################################
#
#    MiiG Solution
#
#    Copyright (C) 2026-TODAY MiiG Solution(<https://www.miigsolution.so>)
#    Author: MiiG Solution(<https://www.miigsolution.so>)
#
#    You can modify it under the terms of the GNU LESSER
#    GENERAL PUBLIC LICENSE (LGPL v3), Version 3.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU LESSER GENERAL PUBLIC LICENSE (LGPL v3) for more details.
#
#    You should have received a copy of the GNU LESSER GENERAL PUBLIC LICENSE
#    (LGPL v3) along with this program.
#    If not, see <http://www.gnu.org/licenses/>.
#
#############################################################################
from datetime import date, datetime, timedelta
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class HotelNightAudit(models.Model):
    """Daily Hotel Night/Day Audit record consolidating daily hotel operations and reporting."""
    _name = 'hotel.night.audit'
    _description = 'Hotel Night Audit'
    _order = 'date desc, id desc'

    def _default_audit_date(self):
        # Default to yesterday for Night Audit
        return fields.Date.context_today(self) - timedelta(days=1)

    name = fields.Char(string='Audit Reference', required=True, copy=False, readonly=True,
                       default=lambda self: _('New'))
    date = fields.Date(string='Audit Date', required=True, default=_default_audit_date,
                       help="The date for which this audit is performed (usually yesterday).")
    audit_type = fields.Selection([
        ('night', 'Night Audit'),
        ('day', 'Day Audit'),
    ], string='Audit Type', default='night', required=True)
    company_id = fields.Many2one('res.company', string='Company', required=True,
                                 default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id', string='Currency')
    user_id = fields.Many2one('res.users', string='Audited / Printed By', required=True,
                              default=lambda self: self.env.user)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('done', 'Audited / Closed'),
    ], string='Status', default='draft', required=True, tracking=True)

    # Operational KPI Summary Fields
    total_checkin_count = fields.Integer(string='Check-Ins', readonly=True)
    total_checkout_count = fields.Integer(string='Check-Outs', readonly=True)
    inhouse_count = fields.Integer(string='In-House Guests', readonly=True)
    daily_room_revenue = fields.Monetary(string='Daily Room Rent', currency_field='currency_id', readonly=True)
    daily_pos_revenue = fields.Monetary(string='Daily POS / Rest Revenue', currency_field='currency_id', readonly=True)
    daily_total_revenue = fields.Monetary(string='Total Day Revenue', currency_field='currency_id', readonly=True)

    _sql_constraints = [
        ('date_type_company_uniq', 'unique(date, audit_type, company_id)',
         'An audit record of this type already exists for the selected date and company!'),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('New'):
                audit_date = vals.get('date') or fields.Date.today()
                audit_type = vals.get('audit_type', 'night').capitalize()
                vals['name'] = f"{audit_type} Audit - {audit_date}"
        records = super().create(vals_list)
        for record in records:
            if record.state == 'draft':
                record.action_generate_audit()
        return records

    def action_generate_audit(self):
        """Compile statistics and metrics for the selected audit date."""
        for rec in self:
            data = rec.get_audit_report_data()
            kpis = data.get('kpis', {})
            rec.write({
                'total_checkin_count': kpis.get('checkin_count', 0),
                'total_checkout_count': kpis.get('checkout_count', 0),
                'inhouse_count': kpis.get('inhouse_count', 0),
                'daily_room_revenue': kpis.get('room_revenue', 0.0),
                'daily_pos_revenue': kpis.get('pos_revenue', 0.0),
                'daily_total_revenue': kpis.get('total_revenue', 0.0),
                'state': 'done',
            })
        return True

    def action_reset_draft(self):
        """Reset the audit record back to draft to allow re-running."""
        self.write({'state': 'draft'})

    def action_print_report(self):
        """Print the complete 5-in-1 consolidated PDF Night Audit Pack."""
        self.ensure_one()
        return self.env.ref('hotel_management_odoo.action_report_night_audit').report_action(self)

    def get_audit_report_data(self):
        """Fetch and package all 5 audit report sections for the audit date."""
        self.ensure_one()
        target_date = self.date
        start_dt = datetime.combine(target_date, datetime.min.time())
        end_dt = datetime.combine(target_date, datetime.max.time())

        # 1. Check-In Report (Bookings that checked in on this date)
        checkin_bookings = self.env['room.booking'].search([
            ('company_id', '=', self.company_id.id),
            ('checkin_date', '>=', start_dt),
            ('checkin_date', '<=', end_dt),
            ('state', 'in', ['check_in', 'check_out', 'done']),
        ])
        checkin_list = []
        for b in checkin_bookings:
            room_names = ", ".join(b.room_line_ids.mapped('room_id.name'))
            daily_rate = sum(b.room_line_ids.mapped('price_unit'))
            checkin_list.append({
                'booking_no': b.name,
                'guest_name': b.partner_id.name if b.partner_id else '',
                'room': room_names or 'N/A',
                'checkin': b.checkin_date,
                'checkout': b.checkout_date,
                'duration': b.duration,
                'board_type': dict(b._fields['board_type'].selection).get(b.board_type, b.board_type),
                'daily_rate': daily_rate,
                'total_amount': b.amount_total,
                'state': dict(b._fields['state'].selection).get(b.state, b.state),
            })

        # 2. Check-Out Report (Bookings that checked out on this date)
        checkout_bookings = self.env['room.booking'].search([
            ('company_id', '=', self.company_id.id),
            ('checkout_date', '>=', start_dt),
            ('checkout_date', '<=', end_dt),
            ('state', 'in', ['check_out', 'done']),
        ])
        checkout_list = []
        for b in checkout_bookings:
            room_names = ", ".join(b.room_line_ids.mapped('room_id.name'))
            checkout_list.append({
                'booking_no': b.name,
                'guest_name': b.partner_id.name if b.partner_id else '',
                'room': room_names or 'N/A',
                'checkin': b.checkin_date,
                'checkout': b.checkout_date,
                'duration': b.duration,
                'total_amount': b.amount_total,
                'state': dict(b._fields['state'].selection).get(b.state, b.state),
            })

        # 3. In-House Guest List (Active checked-in guests on this date)
        # Guests checked in before/on target_date and checkout after target_date or still in check_in
        inhouse_bookings = self.env['room.booking'].search([
            ('company_id', '=', self.company_id.id),
            ('checkin_date', '<=', end_dt),
            ('state', '=', 'check_in'),
        ])
        inhouse_list = []
        total_inhouse_rent = 0.0
        for b in inhouse_bookings:
            room_names = ", ".join(b.room_line_ids.mapped('room_id.name'))
            pos_amt = getattr(b, 'amount_total_pos', 0.0) or 0.0
            daily_rent = sum(b.room_line_ids.mapped('price_unit'))
            total_inhouse_rent += daily_rent
            inhouse_list.append({
                'booking_no': b.name,
                'guest_name': b.partner_id.name if b.partner_id else '',
                'room': room_names or 'N/A',
                'checkin': b.checkin_date,
                'checkout': b.checkout_date,
                'daily_rent': daily_rent,
                'pos_charges': pos_amt,
                'total_due_today': getattr(b, 'amount_due_today', b.amount_total) or b.amount_total,
            })

        # 4. Daily POS / Restaurant Orders on target date
        pos_orders = self.env['pos.order'].search([
            ('company_id', '=', self.company_id.id),
            ('date_order', '>=', start_dt),
            ('date_order', '<=', end_dt),
            ('state', 'not in', ['cancel', 'draft']),
        ])
        pos_list = []
        total_pos_revenue = sum(pos_orders.mapped('amount_total'))
        for po in pos_orders:
            pos_list.append({
                'receipt': po.pos_reference or po.name,
                'booking': po.booking_id.name if hasattr(po, 'booking_id') and po.booking_id else 'Direct / Walk-in',
                'guest': po.partner_id.name if po.partner_id else 'Walk-In Guest',
                'time': po.date_order,
                'cashier': po.user_id.name if po.user_id else '',
                'amount': po.amount_total,
                'status': dict(po._fields['state'].selection).get(po.state, po.state),
            })

        # 5. Guest Ledger / Open Folio Balances
        ledger_bookings = self.env['room.booking'].search([
            ('company_id', '=', self.company_id.id),
            ('state', 'in', ['check_in', 'check_out']),
        ])
        ledger_list = []
        for b in ledger_bookings:
            pos_amt = getattr(b, 'amount_total_pos', 0.0) or 0.0
            room_charges = sum(b.room_line_ids.mapped('price_total'))
            food_charges = sum(b.food_order_line_ids.mapped('price_total'))
            service_charges = sum(b.service_line_ids.mapped('price_total'))
            fleet_charges = sum(b.vehicle_line_ids.mapped('price_total'))
            event_charges = sum(b.event_line_ids.mapped('price_total'))
            total_folio = room_charges + food_charges + service_charges + fleet_charges + event_charges + pos_amt

            ledger_list.append({
                'booking_no': b.name,
                'guest_name': b.partner_id.name if b.partner_id else '',
                'room': b.room_number or 'N/A',
                'room_charges': room_charges,
                'pos_charges': pos_amt,
                'other_services': food_charges + service_charges + fleet_charges + event_charges,
                'total_folio': total_folio,
                'status': dict(b._fields['state'].selection).get(b.state, b.state),
            })

        # Daily Revenue KPIs
        daily_room_revenue = total_inhouse_rent
        daily_total_revenue = daily_room_revenue + total_pos_revenue

        return {
            'audit': self,
            'company': self.company_id,
            'currency': self.currency_id,
            'kpis': {
                'checkin_count': len(checkin_list),
                'checkout_count': len(checkout_list),
                'inhouse_count': len(inhouse_list),
                'room_revenue': daily_room_revenue,
                'pos_revenue': total_pos_revenue,
                'total_revenue': daily_total_revenue,
            },
            'checkins': checkin_list,
            'checkouts': checkout_list,
            'inhouse': inhouse_list,
            'pos_orders': pos_list,
            'guest_ledger': ledger_list,
        }
