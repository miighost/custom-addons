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
#############################################################################
import io
import json
from datetime import datetime, timedelta
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import json_default

try:
    from odoo.tools.misc import xlsxwriter
except ImportError:
    import xlsxwriter


class HotelOperationalReportWizard(models.TransientModel):
    """Wizard for running individual Hotel Operational Reports on-demand."""
    _name = "hotel.operational.report.wizard"
    _description = "Hotel Operational Report Wizard"

    report_type = fields.Selection([
        ('inhouse', 'In House Guest List'),
        ('room_analysis', 'Room Analysis Summary'),
        ('checkin', 'Daily Check-In / Arrivals Report'),
        ('checkout', 'Daily Check-Out / Departures Report'),
        ('daily_rent', 'Daily Rent / Room Charges'),
        ('cash_report', 'Cash & Collections Report'),
        ('guest_ledger', 'Guest Ledger & Open Balances'),
    ], string="Report Type", required=True, default='inhouse')

    date_from = fields.Date(string="From Date", required=True, default=fields.Date.context_today)
    date_to = fields.Date(string="To Date", required=True, default=fields.Date.context_today)
    company_id = fields.Many2one('res.company', string='Company', required=True,
                                 default=lambda self: self.env.company)

    @api.onchange('date_from')
    def _onchange_date_from(self):
        if self.date_from and not self.date_to:
            self.date_to = self.date_from

    def action_print_pdf(self):
        """Generate PDF for the selected report type."""
        self.ensure_one()
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValidationError(_("From Date cannot be greater than To Date."))

        report_data = self.get_report_data()
        data = {
            'wizard': self.read()[0],
            'report_data': report_data,
        }
        return self.env.ref('hotel_management_odoo.action_report_hotel_operational').report_action(self, data=data)

    def get_report_data(self):
        """Compile data for the requested report type and date range."""
        self.ensure_one()
        start_dt = datetime.combine(self.date_from, datetime.min.time())
        end_dt = datetime.combine(self.date_to, datetime.max.time())
        company_id = self.company_id.id

        total_rooms = self.env['product.product'].search_count([('is_room', '=', True)])
        if total_rooms == 0:
            total_rooms = self.env['product.template'].search_count([('is_room', '=', True)])
        maintenance_rooms = self.env['product.product'].search_count([
            ('is_room', '=', True), ('status', 'in', ['maintenance', 'cleaning'])
        ])

        # 1. In-House Guest List
        inhouse_bookings = self.env['room.booking'].search([
            ('company_id', '=', company_id),
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

            inhouse_list.append({
                's_no': idx,
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
            })

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

        # 2. Check-In / Arrivals
        checkin_bookings = self.env['room.booking'].search([
            ('company_id', '=', company_id),
            ('checkin_date', '>=', start_dt),
            ('checkin_date', '<=', end_dt),
            ('state', 'in', ['check_in', 'check_out', 'done']),
        ])
        checkin_list = []
        for idx, b in enumerate(checkin_bookings, 1):
            room_names = b.room_number or ", ".join(b.room_line_ids.mapped('room_id.name'))
            daily_rate = sum(b.room_line_ids.mapped('price_unit'))
            pax = len(b.room_line_ids) or 1
            company_name = b.partner_id.parent_id.name or 'Walk In Guest'
            nationality = b.partner_id.country_id.name if b.partner_id and b.partner_id.country_id else 'N/A'
            board_label = dict(b._fields['board_type'].selection).get(b.board_type, 'Room Only')

            checkin_list.append({
                's_no': idx,
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
            })

        # 3. Check-Out / Departures
        checkout_bookings = self.env['room.booking'].search([
            ('company_id', '=', company_id),
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
            })

        # 4. Cash & Collections
        pos_orders = self.env['pos.order'].search([
            ('company_id', '=', company_id),
            ('date_order', '>=', start_dt),
            ('date_order', '<=', end_dt),
            ('state', 'not in', ['cancel', 'draft']),
        ])
        cash_report_list = []
        running_bal = 0.0
        for idx, po in enumerate(pos_orders, 1):
            guest_name = po.partner_id.name if po.partner_id else 'OUTSIDE GUEST'
            room_no = getattr(po, 'room_number', '') or (po.booking_id.room_number if hasattr(po, 'booking_id') and po.booking_id else '')
            card_no = po.booking_id.name if hasattr(po, 'booking_id') and po.booking_id else ''
            running_bal += po.amount_total
            pay_method = po.payment_ids[0].payment_method_id.name if po.payment_ids and po.payment_ids[0].payment_method_id else 'CASH'

            cash_report_list.append({
                's_no': idx,
                'date_time': po.date_order.strftime('%d/%m %I:%M %p') if po.date_order else '',
                'method': pay_method,
                'name': guest_name,
                'voucher_no': po.pos_reference or po.name,
                'remarks': 'RESTAURANT SALE' if not card_no else f'Folio ({card_no})',
                'card_no': card_no or '-',
                'room_no': room_no or '-',
                'debit': po.amount_total,
                'credit': 0.0,
                'balance': running_bal,
            })

        # 5. Guest Ledger
        ledger_bookings = self.env['room.booking'].search([
            ('company_id', '=', company_id),
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
            })

        # 6. Room Analysis KPIs
        occupied_rooms = len(inhouse_list)
        vacant_rooms = max(0, total_rooms - occupied_rooms - maintenance_rooms)
        arr = round(total_inhouse_rent / occupied_rooms, 2) if occupied_rooms > 0 else 0.0
        revpar = round(total_inhouse_rent / total_rooms, 2) if total_rooms > 0 else 0.0
        occupancy_rate = round((occupied_rooms / total_rooms) * 100, 2) if total_rooms > 0 else 0.0
        avg_guest_rate = round(total_inhouse_rent / total_pax, 2) if total_pax > 0 else 0.0

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
            'checkin_today': len(checkin_list),
            'checkout_today': len(checkout_list),
            'room_revenue': total_inhouse_rent,
            'pos_revenue': sum(po.amount_total for po in pos_orders),
            'total_revenue': total_inhouse_rent + sum(po.amount_total for po in pos_orders),
        }

        return {
            'currency': self.company_id.currency_id,
            'inhouse': inhouse_list,
            'daily_rent': daily_rent_list,
            'checkins': checkin_list,
            'checkouts': checkout_list,
            'cash_report': cash_report_list,
            'guest_ledger': ledger_list,
            'room_analysis': room_analysis,
        }
