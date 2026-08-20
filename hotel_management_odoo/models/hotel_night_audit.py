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
#    This program is distributed in the hope it will be useful,
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
    """Daily Hotel Night Audit record consolidating daily hotel operations and reporting."""
    _name = 'hotel.night.audit'
    _description = 'Hotel Night Audit'
    _order = 'date desc, id desc'

    def _default_audit_date(self):
        # Default to yesterday for Night Audit
        return fields.Date.context_today(self) - timedelta(days=1)

    name = fields.Char(string='Audit Reference', required=True, copy=False, readonly=True,
                       default=lambda self: _('New'))
    date = fields.Date(string='Audit Date', required=True, default=_default_audit_date,
                       help="The 24-hour date for which this night audit is performed (defaults to yesterday).")
    audit_type = fields.Selection([
        ('night', 'Night Audit'),
    ], string='Audit Type', default='night', required=True)
    company_id = fields.Many2one('res.company', string='Company', required=True,
                                 default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id', string='Currency')
    user_id = fields.Many2one('res.users', string='Audited / Printed By', required=True, readonly=True,
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
        ('date_company_uniq', 'unique(date, company_id)',
         'A Night Audit record already exists for the selected date and company!'),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('New'):
                audit_date = vals.get('date') or fields.Date.today()
                vals['name'] = f"Night Audit - {audit_date}"
                vals['user_id'] = self.env.uid
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
        """Print the complete consolidated PDF Night Audit Pack."""
        self.ensure_one()
        return self.env.ref('hotel_management_odoo.action_report_night_audit').report_action(self)

    def get_audit_report_data(self):
        """Fetch and package all audit report sections matching hotel industry standard tables."""
        self.ensure_one()
        target_date = self.date
        start_dt = datetime.combine(target_date, datetime.min.time())
        end_dt = datetime.combine(target_date, datetime.max.time())

        # Total room capacity metrics
        total_rooms = self.env['product.product'].search_count([('is_room', '=', True)])
        if total_rooms == 0:
            total_rooms = self.env['product.template'].search_count([('is_room', '=', True)])
        maintenance_rooms = self.env['product.product'].search_count([
            ('is_room', '=', True), ('status', 'in', ['maintenance', 'cleaning'])
        ])

        # -------------------------------------------------------------
        # 1. Check-In Report (Arrivals on this 24-hour date)
        # -------------------------------------------------------------
        checkin_bookings = self.env['room.booking'].search([
            ('company_id', '=', self.company_id.id),
            ('checkin_date', '>=', start_dt),
            ('checkin_date', '<=', end_dt),
            ('state', 'in', ['check_in', 'check_out', 'done']),
        ])
        checkin_list = []
        for idx, b in enumerate(checkin_bookings, 1):
            room_names = b.room_number or ", ".join(b.room_line_ids.mapped('room_id.name'))
            daily_rate = sum(b.room_line_ids.mapped('price_unit'))
            pax = len(b.room_line_ids) or 1
            company_name = b.partner_id.parent_id.name or (b.partner_id.company_name if hasattr(b.partner_id, 'company_name') else '') or 'Walk-In Guest'
            nationality = b.partner_id.country_id.name if b.partner_id and b.partner_id.country_id else 'N/A'
            board_label = dict(b._fields['board_type'].selection).get(b.board_type, 'Room Only')

            checkin_list.append({
                's_no': idx,
                'booking_no': b.name,
                'guest_name': b.partner_id.name if b.partner_id else 'Guest',
                'room': room_names or 'N/A',
                'pax': pax,
                'card_no': b.name,
                'company': company_name,
                'rate': daily_rate,
                'in_date': b.checkin_date.strftime('%d/%m/%Y') if b.checkin_date else '',
                'in_time': b.checkin_date.strftime('%I:%M %p') if b.checkin_date else '',
                'plan': board_label,
                'nationality': nationality,
                'total_amount': b.amount_total,
                'state': dict(b._fields['state'].selection).get(b.state, b.state),
            })

        # -------------------------------------------------------------
        # 2. Check-Out Report (Departures on this 24-hour date) - Image 3
        # -------------------------------------------------------------
        checkout_bookings = self.env['room.booking'].search([
            ('company_id', '=', self.company_id.id),
            ('checkout_date', '>=', start_dt),
            ('checkout_date', '<=', end_dt),
            ('state', 'in', ['check_out', 'done']),
        ])
        checkout_list = []
        for idx, b in enumerate(checkout_bookings, 1):
            room_names = b.room_number or ", ".join(b.room_line_ids.mapped('room_id.name'))
            daily_rate = sum(b.room_line_ids.mapped('price_unit'))
            pax = len(b.room_line_ids) or 1
            company_name = b.partner_id.parent_id.name or 'Direct Account'

            # Find invoice number if invoiced
            invoices = self.env['account.move'].search([('ref', '=', b.name)], limit=1)
            invoice_no = invoices.name if invoices else b.name

            checkout_list.append({
                's_no': idx,
                'guest_name': b.partner_id.name if b.partner_id else 'Guest',
                'room_no': room_names or 'N/A',
                'pax': pax,
                'card_no': b.name,
                'invoice_no': invoice_no,
                'company': company_name,
                'rate': daily_rate,
                'in_date': b.checkin_date.strftime('%d/%m/%Y') if b.checkin_date else '',
                'in_time': b.checkin_date.strftime('%I:%M %p') if b.checkin_date else '',
                'out_date': b.checkout_date.strftime('%d/%m/%Y') if b.checkout_date else '',
                'out_time': b.checkout_date.strftime('%I:%M %p') if b.checkout_date else '',
                'total_amount': b.amount_total,
            })

        # -------------------------------------------------------------
        # 3. In-House Guest List (Active Checked-In Guests) - Image 1
        # -------------------------------------------------------------
        inhouse_bookings = self.env['room.booking'].search([
            ('company_id', '=', self.company_id.id),
            ('checkin_date', '<=', end_dt),
            ('state', '=', 'check_in'),
        ])
        inhouse_list = []
        daily_rent_list = []
        total_inhouse_rent = 0.0
        total_pax = 0

        for idx, b in enumerate(inhouse_bookings, 1):
            room_names = b.room_number or ", ".join(b.room_line_ids.mapped('room_id.name'))
            daily_rent = sum(b.room_line_ids.mapped('price_unit'))
            total_inhouse_rent += daily_rent
            pax = len(b.room_line_ids) or 1
            total_pax += pax
            company_name = b.partner_id.parent_id.name or (b.partner_id.company_name if hasattr(b.partner_id, 'company_name') else '') or 'Walk In Guest'
            nationality = b.partner_id.country_id.name if b.partner_id and b.partner_id.country_id else 'SOMALIA'
            board_label = dict(b._fields['board_type'].selection).get(b.board_type, 'Room Only')

            inhouse_entry = {
                'rm_no': room_names or 'N/A',
                'name': b.partner_id.name if b.partner_id else 'Guest',
                'pax': pax,
                'checkin': b.checkin_date.strftime('%d/%m/%Y') if b.checkin_date else '',
                'checkout': b.checkout_date.strftime('%d/%m/%Y') if b.checkout_date else '',
                'plan': board_label,
                'reg': b.name,
                'nationality': nationality,
                'city_ledger': company_name,
                'room_rate': daily_rent,
            }
            inhouse_list.append(inhouse_entry)

            # Daily Rent Entry - Image 4
            daily_rent_list.append({
                's_no': idx,
                'name': b.partner_id.name if b.partner_id else 'Guest',
                'room_no': room_names or 'N/A',
                'card_no': b.name,
                'checkin': b.checkin_date.strftime('%d/%m/%Y') if b.checkin_date else '',
                'pax': pax,
                'company_name': company_name,
                'rent': daily_rent,
            })

        # -------------------------------------------------------------
        # 4. Daily POS / Restaurant & Cash Transactions - Image 5
        # -------------------------------------------------------------
        pos_orders = self.env['pos.order'].search([
            ('company_id', '=', self.company_id.id),
            ('date_order', '>=', start_dt),
            ('date_order', '<=', end_dt),
            ('state', 'not in', ['cancel', 'draft']),
        ])
        pos_list = []
        cash_report_list = []
        total_pos_revenue = sum(pos_orders.mapped('amount_total'))

        running_balance = 0.0
        for idx, po in enumerate(pos_orders, 1):
            guest_name = po.partner_id.name if po.partner_id else 'OUTSIDE GUEST'
            room_no = getattr(po, 'room_number', '') or (po.booking_id.room_number if hasattr(po, 'booking_id') and po.booking_id else '')
            card_no = po.booking_id.name if hasattr(po, 'booking_id') and po.booking_id else ''
            running_balance += po.amount_total

            # Get payment method name if available
            pay_method = 'CASH'
            if po.payment_ids:
                pay_method = po.payment_ids[0].payment_method_id.name if po.payment_ids[0].payment_method_id else 'CASH'

            cash_report_list.append({
                's_no': idx,
                'date_time': po.date_order.strftime('%d/%m %I:%M %p') if po.date_order else '',
                'method': pay_method,
                'name': guest_name,
                'voucher_no': po.pos_reference or po.name,
                'remarks': 'RESTAURANT SALE' if not card_no else f'Folio Charge ({card_no})',
                'card_no': card_no or '-',
                'room_no': room_no or '-',
                'debit': po.amount_total,
                'credit': 0.0,
                'balance': running_balance,
            })

            pos_list.append({
                'receipt': po.pos_reference or po.name,
                'booking': po.booking_id.name if hasattr(po, 'booking_id') and po.booking_id else 'Direct / Walk-in',
                'guest': guest_name,
                'time': po.date_order,
                'cashier': po.user_id.name if po.user_id else '',
                'amount': po.amount_total,
                'status': dict(po._fields['state'].selection).get(po.state, po.state),
            })

        # -------------------------------------------------------------
        # 5. Guest Ledger / Open Balances
        # -------------------------------------------------------------
        ledger_bookings = self.env['room.booking'].search([
            ('company_id', '=', self.company_id.id),
            ('state', 'in', ['check_in', 'check_out']),
        ])
        ledger_list = []
        for idx, b in enumerate(ledger_bookings, 1):
            pos_amt = getattr(b, 'amount_total_pos', 0.0) or 0.0
            room_charges = sum(b.room_line_ids.mapped('price_total'))
            food_charges = sum(b.food_order_line_ids.mapped('price_total'))
            service_charges = sum(b.service_line_ids.mapped('price_total'))
            fleet_charges = sum(b.vehicle_line_ids.mapped('price_total'))
            event_charges = sum(b.event_line_ids.mapped('price_total'))
            total_folio = room_charges + food_charges + service_charges + fleet_charges + event_charges + pos_amt

            company_name = b.partner_id.parent_id.name or 'Direct Account'

            ledger_list.append({
                's_no': idx,
                'booking_no': b.name,
                'guest_name': b.partner_id.name if b.partner_id else 'Guest',
                'room': b.room_number or 'N/A',
                'company': company_name,
                'checkin': b.checkin_date.strftime('%d/%m/%Y') if b.checkin_date else '',
                'checkout': b.checkout_date.strftime('%d/%m/%Y') if b.checkout_date else '',
                'room_charges': room_charges,
                'pos_charges': pos_amt,
                'other_services': food_charges + service_charges + fleet_charges + event_charges,
                'total_folio': total_folio,
                'status': dict(b._fields['state'].selection).get(b.state, b.state),
            })

        # -------------------------------------------------------------
        # 6. Room Analysis Summary KPIs - Image 2
        # -------------------------------------------------------------
        occupied_rooms = len(inhouse_list)
        vacant_rooms = max(0, total_rooms - occupied_rooms - maintenance_rooms)
        arr = round(total_inhouse_rent / occupied_rooms, 2) if occupied_rooms > 0 else 0.0
        revpar = round(total_inhouse_rent / total_rooms, 2) if total_rooms > 0 else 0.0
        occupancy_rate = round((occupied_rooms / total_rooms) * 100, 2) if total_rooms > 0 else 0.0
        avg_guest_rate = round(total_inhouse_rent / total_pax, 2) if total_pax > 0 else 0.0

        daily_room_revenue = total_inhouse_rent
        daily_total_revenue = daily_room_revenue + total_pos_revenue

        room_analysis = {
            'occupied': occupied_rooms,
            'vacant': vacant_rooms,
            'repair': maintenance_rooms,
            'house_use': 0,
            'total_rooms': total_rooms,
            'total_avail': total_rooms - maintenance_rooms,
            'arr': arr,
            'guest_inhouse': total_pax,
            'avg_guest_rate': avg_guest_rate,
            'revpar': revpar,
            'occupancy_pct': occupancy_rate,
            'num_reservations': len(checkin_list) + occupied_rooms,
            'checkin_today': len(checkin_list),
            'checkout_today': len(checkout_list),
        }

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
            'room_analysis': room_analysis,
            'checkins': checkin_list,
            'checkouts': checkout_list,
            'inhouse': inhouse_list,
            'daily_rent': daily_rent_list,
            'cash_report': cash_report_list,
            'pos_orders': pos_list,
            'guest_ledger': ledger_list,
        }
