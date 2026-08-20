# -*- coding: utf-8 -*-
#############################################################################
#
#    Cybrosys Technologies Pvt. Ltd.
#
#    Copyright (C) 2026-TODAY Cybrosys Technologies(<https://www.cybrosys.com>)
#    Author: Cybrosys Techno Solutions(<https://www.cybrosys.com>)
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
from datetime import datetime, timedelta
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class RoomBooking(models.Model):
    """Model that handles the hotel room booking and all operations related
     to booking"""
    _name = "room.booking"
    _description = "Hotel Room Reservation"
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string="Folio Number", readonly=True, index=True,
                       default="New", help="Name of Folio")
    company_id = fields.Many2one('res.company', string="Company",
                                 help="Choose the Company",
                                 required=True, index=True,
                                 default=lambda self: self.env.company)
    partner_id = fields.Many2one('res.partner', string="Customer",
                                 help="Customers of hotel",
                                 required=True, index=True, tracking=1,
                                 domain="[('type', '!=', 'private'),"
                                        " ('company_id', 'in', "
                                        "(False, company_id))]")
    date_order = fields.Datetime(string="Order Date",
                                 required=True, copy=False,
                                 help="Creation date of draft/sent orders,"
                                      " Confirmation date of confirmed orders",
                                 default=fields.Datetime.now)
    is_checkin = fields.Boolean(default=False, string="Is Checkin",
                                help="sets to True if the room is occupied")
    maintenance_request_sent = fields.Boolean(default=False,
                                              string="Maintenance Request sent"
                                                     "or Not",
                                              help="sets to True if the "
                                                   "maintenance request send "
                                                   "once")
    checkin_date = fields.Datetime(string="Check In",
                                   help="Date of Checkin",
                                   default=fields.Datetime.now())
    checkout_date = fields.Datetime(string="Check Out",
                                    help="Date of Checkout",
                                    default=fields.Datetime.now() + timedelta(
                                        hours=23, minutes=59, seconds=59))
    hotel_policy = fields.Selection([("prepaid", "On Booking"),
                                     ("manual", "On Check In"),
                                     ("picking", "On Checkout"),
                                     ],
                                    default="manual", string="Hotel Policy",
                                    help="Hotel policy for payment that "
                                         "either the guest has to pay at "
                                         "booking time, check-in "
                                         "or check-out time.", tracking=True)
    duration = fields.Integer(string="Duration in Days",
                              help="Number of days which will automatically "
                                   "count from the check-in and check-out "
                                   "date.", )
    invoice_button_visible = fields.Boolean(string='Invoice Button Display',
                                            help="Invoice button will be "
                                                 "visible if this button is "
                                                 "True")
    invoice_status = fields.Selection(
        selection=[('no_invoice', 'Nothing To Invoice'),
                   ('to_invoice', 'To Invoice'),
                   ('invoiced', 'Invoiced'),
                   ], string="Invoice Status",
        help="Status of the Invoice",
        default='no_invoice', tracking=True)
    hotel_invoice_id = fields.Many2one("account.move",
                                       string="Invoice",
                                       help="Indicates the invoice",
                                       copy=False)
    duration_visible = fields.Float(string="Duration",
                                    help="A dummy field for Duration")
    need_service = fields.Boolean(default=False, string="Need Service",
                                  help="Check if a Service to be added with"
                                       " the Booking")
    need_fleet = fields.Boolean(default=False, string="Need Vehicle",
                                help="Check if a Fleet to be"
                                     " added with the Booking")
    need_food = fields.Boolean(default=False, string="Need Food",
                               help="Check if a Food to be added with"
                                    " the Booking")
    need_event = fields.Boolean(default=False, string="Need Event",
                                help="Check if a Event to be added with"
                                     " the Booking")
    service_line_ids = fields.One2many("service.booking.line",
                                       "booking_id",
                                       string="Service",
                                       help="Hotel services details provided to"
                                            "Customer and it will included in "
                                            "the main Invoice.")
    event_line_ids = fields.One2many("event.booking.line",
                                     'booking_id',
                                     string="Event",
                                     help="Hotel event reservation detail.")
    vehicle_line_ids = fields.One2many("fleet.booking.line",
                                       "booking_id",
                                       string="Vehicle",
                                       help="Hotel fleet reservation detail.")
    room_line_ids = fields.One2many("room.booking.line",
                                    "booking_id", string="Room",
                                    help="Hotel room reservation detail.")
    food_order_line_ids = fields.One2many("food.booking.line",
                                          "booking_id",
                                          string='Food',
                                          help="Food details provided"
                                               " to Customer and"
                                               " it will included in the "
                                               "main invoice.", )
    board_type = fields.Selection([
        ('ro', 'Room Only (RO)'),
        ('bb', 'Bed & Breakfast (BB)'),
        ('hb', 'Half Board (HB)'),
        ('fb', 'Full Board (FB)'),
    ], string='Board Type', default='ro', help="Select the meal plan / board type for this booking.")
    room_number = fields.Char(string="Room No.", compute="_compute_room_number", store=True)
    amount_due_today = fields.Monetary(string="Total Due Today", compute="_compute_amount_due_today", store=False,
                                      help="Total accrued balance up to today including room charges and all services/POS.")

    @api.depends('room_line_ids.todays_balance', 'food_order_line_ids.price_total',
                 'service_line_ids.price_total', 'vehicle_line_ids.price_total',
                 'event_line_ids.price_total')
    def _compute_amount_due_today(self):
        for rec in self:
            pos_amt = getattr(rec, 'amount_total_pos', 0.0) or 0.0
            room_today = sum(rec.room_line_ids.mapped('todays_balance'))
            food_total = sum(rec.food_order_line_ids.mapped('price_total'))
            service_total = sum(rec.service_line_ids.mapped('price_total'))
            fleet_total = sum(rec.vehicle_line_ids.mapped('price_total'))
            event_total = sum(rec.event_line_ids.mapped('price_total'))
            rec.amount_due_today = room_today + pos_amt + food_total + service_total + fleet_total + event_total

    @api.depends('room_line_ids.room_id')
    def _compute_room_number(self):
        for record in self:
            valid_rooms = record.room_line_ids.filtered(lambda l: l.room_id and l.room_id.exists()).mapped('room_id.name')
            record.room_number = ", ".join(valid_rooms) if valid_rooms else ""

    state = fields.Selection(selection=[('draft', 'Draft'),
                                        ('reserved', 'Reserved'),
                                        ('check_in', 'Check In'),
                                        ('check_out', 'Check Out'),
                                        ('cancel', 'Cancelled'),
                                        ('done', 'Done')], string='State',
                             help="State of the Booking",
                             default='draft', tracking=True)
    user_id = fields.Many2one(comodel_name='res.partner',
                              string="Invoice Address",
                              compute='_compute_user_id',
                              help="Sets the User automatically",
                              required=True,
                              domain="['|', ('company_id', '=', False), "
                                     "('company_id', '=',"
                                     " company_id)]")
    pricelist_id = fields.Many2one(comodel_name='product.pricelist',
                                   string="Pricelist",
                                   compute='_compute_pricelist_id',
                                   store=True, readonly=False,
                                   required=True,
                                   tracking=1,
                                   help="If you change the pricelist,"
                                        " only newly added lines"
                                        " will be affected.")
    currency_id = fields.Many2one(
        string="Currency", help="This is the Currency used",
        related='pricelist_id.currency_id',
        depends=['pricelist_id.currency_id'],
    )
    invoice_count = fields.Integer(compute='_compute_invoice_count',
                                   string="Invoice "
                                          "Count",
                                   help="The number of invoices created")
    account_move = fields.Integer(string='Invoice Id',
                                  help="Id of the invoice created")
    amount_untaxed = fields.Monetary(string="Total Untaxed Amount",
                                     help="This indicates the total untaxed "
                                          "amount", store=True,
                                     compute='_compute_amount_untaxed',
                                     tracking=5)
    amount_tax = fields.Monetary(string="Taxes", help="Total Tax Amount",
                                 store=True, compute='_compute_amount_untaxed')
    amount_total = fields.Monetary(string="Total", store=True,
                                   help="The total Amount including Tax",
                                   compute='_compute_amount_untaxed',
                                   tracking=4)
    amount_untaxed_room = fields.Monetary(string="Room Untaxed",
                                          help="Untaxed Amount for Room",
                                          compute='_compute_amount_untaxed',
                                          tracking=5)
    amount_untaxed_food = fields.Monetary(string="Food Untaxed",
                                          help="Untaxed Amount for Food",
                                          compute='_compute_amount_untaxed',
                                          tracking=5)
    amount_untaxed_event = fields.Monetary(string="Event Untaxed",
                                           help="Untaxed Amount for Event",
                                           compute='_compute_amount_untaxed',
                                           tracking=5)
    amount_untaxed_service = fields.Monetary(
        string="Service Untaxed", help="Untaxed Amount for Service",
        compute='_compute_amount_untaxed', tracking=5)
    amount_untaxed_fleet = fields.Monetary(string="Amount Untaxed",
                                           help="Untaxed amount for Fleet",
                                           compute='_compute_amount_untaxed',
                                           tracking=5)
    amount_taxed_room = fields.Monetary(string="Rom Tax", help="Tax for Room",
                                        compute='_compute_amount_untaxed',
                                        tracking=5)
    amount_taxed_food = fields.Monetary(string="Food Tax", help="Tax for Food",
                                        compute='_compute_amount_untaxed',
                                        tracking=5)
    amount_taxed_event = fields.Monetary(string="Event Tax",
                                         help="Tax for Event",
                                         compute='_compute_amount_untaxed',
                                         tracking=5)
    amount_taxed_service = fields.Monetary(string="Service Tax",
                                           compute='_compute_amount_untaxed',
                                           help="Tax for Service", tracking=5)
    amount_taxed_fleet = fields.Monetary(string="Fleet Tax",
                                         compute='_compute_amount_untaxed',
                                         help="Tax for Fleet", tracking=5)
    amount_total_room = fields.Monetary(string="Total Amount for Room",
                                        compute='_compute_amount_untaxed',
                                        help="This is the Total Amount for "
                                             "Room", tracking=5)
    amount_total_food = fields.Monetary(string="Total Amount for Food",
                                        compute='_compute_amount_untaxed',
                                        help="This is the Total Amount for "
                                             "Food", tracking=5)
    amount_total_event = fields.Monetary(string="Total Amount for Event",
                                         compute='_compute_amount_untaxed',
                                         help="This is the Total Amount for "
                                              "Event", tracking=5)
    amount_total_service = fields.Monetary(string="Total Amount for Service",
                                           compute='_compute_amount_untaxed',
                                           help="This is the Total Amount for "
                                                "Service", tracking=5)
    amount_total_fleet = fields.Monetary(string="Total Amount for Fleet",
                                         compute='_compute_amount_untaxed',
                                         help="This is the Total Amount for "
                                              "Fleet", tracking=5)
    has_pos_orders = fields.Boolean(compute='_compute_has_pos_orders', string='Has POS Orders',
                                    help='Indicates if there are POS orders linked to this booking')

    def _compute_has_pos_orders(self):
        """Compute POS order availability."""
        for rec in self:
            rec.has_pos_orders = False

    @api.model_create_multi
    def create(self, vals_list):
        """Sequence Generation with automatic fallback"""
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') in ['New', 'Unnamed']:
                seq_name = self.env['ir.sequence'].next_by_code('room.booking')
                if not seq_name:
                    # Fallback sequence creation if sequence is missing in DB
                    seq = self.env['ir.sequence'].sudo().search([('code', '=', 'room.booking')], limit=1)
                    if not seq:
                        seq = self.env['ir.sequence'].sudo().create({
                            'name': 'Hotel Folio',
                            'code': 'room.booking',
                            'prefix': 'BOOKING/%(year)s/',
                            'padding': 5,
                            'company_id': False,
                        })
                    seq_name = seq.next_by_id() or f"BOOKING/{fields.Date.today().year}/00001"
                vals['name'] = seq_name
        return super().create(vals_list)

    @api.depends('name')
    def _compute_display_name(self):
        for record in self:
            if not record.name or record.name in ['New', 'Unnamed']:
                seq_name = self.env['ir.sequence'].next_by_code('room.booking') or f"BOOKING/{record.id:05d}"
                record.sudo().write({'name': seq_name})
            record.display_name = record.name

    @api.depends('partner_id')
    def _compute_user_id(self):
        """Computes the User id"""
        for order in self:
            order.user_id = \
                order.partner_id.address_get(['invoice'])[
                    'invoice'] if order.partner_id else False

    def _compute_invoice_count(self):
        """Compute the invoice count"""
        for record in self:
            record.invoice_count = self.env['account.move'].search_count(
                [('ref', '=', record.name)])

    @api.depends('partner_id')
    def _compute_pricelist_id(self):
        """Computes PriceList"""
        for order in self:
            if not order.partner_id:
                order.pricelist_id = False
                continue
            order = order.with_company(order.company_id)
            order.pricelist_id = order.partner_id.property_product_pricelist

    @api.depends('room_line_ids.price_subtotal', 'room_line_ids.price_tax',
                 'room_line_ids.price_total',
                 'food_order_line_ids.price_subtotal',
                 'food_order_line_ids.price_tax',
                 'food_order_line_ids.price_total',
                 'service_line_ids.price_subtotal',
                 'service_line_ids.price_tax', 'service_line_ids.price_total',
                 'vehicle_line_ids.price_subtotal',
                 'vehicle_line_ids.price_tax', 'vehicle_line_ids.price_total',
                 'event_line_ids.price_subtotal', 'event_line_ids.price_tax',
                 'event_line_ids.price_total',
                 )
    def _compute_amount_untaxed(self, flag=False):
        """Compute the total amounts of the Sale Order"""
        total_booking_list = []
        for record in self:
            # Map existing invoice lines by name, price, and type to avoid double invoicing
            account_move_lines = self.env['account.move.line'].search([
                ('ref', '=', record.name),
                ('display_type', '!=', 'payment_term')
            ])
            invoiced_map = {}
            for aml in account_move_lines:
                key = (aml.name, aml.price_unit, aml.product_type)
                invoiced_map[key] = invoiced_map.get(key, 0.0) + aml.quantity

            def get_delta(name, qty, price, ptype):
                key = (name, price, ptype)
                already_invoiced = invoiced_map.get(key, 0.0)
                remaining = qty - already_invoiced
                return max(0.0, remaining)

            booking_list = []

            # Rooms
            record.amount_untaxed_room = sum(record.room_line_ids.mapped('price_subtotal'))
            record.amount_taxed_room = sum(record.room_line_ids.mapped('price_tax'))
            record.amount_total_room = sum(record.room_line_ids.mapped('price_total'))
            for room in record.room_line_ids.filtered(lambda l: l.room_id and l.room_id.exists()):
                delta = get_delta(room.room_id.name, room.uom_qty, room.price_unit, 'room')
                if delta > 0:
                    booking_list.append({'name': room.room_id.name, 'quantity': delta, 'price_unit': room.price_unit,
                                         'product_type': 'room'})
                if flag:
                    room.booking_line_visible = True

            # Food
            record.amount_untaxed_food = sum(record.food_order_line_ids.mapped('price_subtotal'))
            record.amount_taxed_food = sum(record.food_order_line_ids.mapped('price_tax'))
            record.amount_total_food = sum(record.food_order_line_ids.mapped('price_total'))
            for food in record.food_order_line_ids:
                delta = get_delta(food.food_id.name, food.uom_qty, food.price_unit, 'food')
                if delta > 0:
                    booking_list.append({'name': food.food_id.name, 'quantity': delta, 'price_unit': food.price_unit,
                                         'product_type': 'food'})

            # Service
            record.amount_untaxed_service = sum(record.service_line_ids.mapped('price_subtotal'))
            record.amount_taxed_service = sum(record.service_line_ids.mapped('price_tax'))
            record.amount_total_service = sum(record.service_line_ids.mapped('price_total'))
            for service in record.service_line_ids:
                delta = get_delta(service.service_id.name, service.uom_qty, service.price_unit, 'service')
                if delta > 0:
                    booking_list.append(
                        {'name': service.service_id.name, 'quantity': delta, 'price_unit': service.price_unit,
                         'product_type': 'service'})

            # Fleet
            record.amount_untaxed_fleet = sum(record.vehicle_line_ids.mapped('price_subtotal'))
            record.amount_taxed_fleet = sum(record.vehicle_line_ids.mapped('price_tax'))
            record.amount_total_fleet = sum(record.vehicle_line_ids.mapped('price_total'))
            for fleet in record.vehicle_line_ids:
                delta = get_delta(fleet.fleet_id.name, fleet.uom_qty, fleet.price_unit, 'fleet')
                if delta > 0:
                    booking_list.append({'name': fleet.fleet_id.name, 'quantity': delta, 'price_unit': fleet.price_unit,
                                         'product_type': 'fleet'})

            # Event
            record.amount_untaxed_event = sum(record.event_line_ids.mapped('price_subtotal'))
            record.amount_taxed_event = sum(record.event_line_ids.mapped('price_tax'))
            record.amount_total_event = sum(record.event_line_ids.mapped('price_total'))
            for event in record.event_line_ids:
                delta = get_delta(event.event_id.name, event.uom_qty, event.price_unit, 'event')
                if delta > 0:
                    booking_list.append({'name': event.event_id.name, 'quantity': delta, 'price_unit': event.price_unit,
                                         'product_type': 'event'})

            record.amount_untaxed = (record.amount_untaxed_room + record.amount_untaxed_food +
                                     record.amount_untaxed_fleet + record.amount_untaxed_event +
                                     record.amount_untaxed_service)
            record.amount_tax = (record.amount_taxed_room + record.amount_taxed_food +
                                 record.amount_taxed_fleet + record.amount_taxed_event +
                                 record.amount_taxed_service)
            record.amount_total = record.amount_untaxed + record.amount_tax

            if flag:
                return booking_list
            total_booking_list.extend(booking_list)
        return total_booking_list

    @api.onchange('need_food')
    def _onchange_need_food(self):
        """Unlink Food Booking Line if Need Food is false"""
        if not self.need_food and self.food_order_line_ids:
            for food in self.food_order_line_ids:
                food.unlink()

    @api.onchange('need_service')
    def _onchange_need_service(self):
        """Unlink Service Booking Line if Need Service is False"""
        if not self.need_service and self.service_line_ids:
            for serv in self.service_line_ids:
                serv.unlink()

    @api.onchange('need_fleet')
    def _onchange_need_fleet(self):
        """Unlink Fleet Booking Line if Need Fleet is False"""
        if not self.need_fleet:
            if self.vehicle_line_ids:
                for fleet in self.vehicle_line_ids:
                    fleet.unlink()

    @api.onchange('need_event')
    def _onchange_need_event(self):
        """Unlink Event Booking Line if Need Event is False"""
        if not self.need_event:
            if self.event_line_ids:
                for event in self.event_line_ids:
                    event.unlink()

    @api.onchange('checkin_date', 'checkout_date')
    def _onchange_checkin_checkout_dates(self):
        """Update duration and sync dates to room lines when checkin/checkout dates are changed."""
        if self.checkout_date and self.checkin_date:
            if self.checkout_date < self.checkin_date:
                raise ValidationError(_("Checkout date must be greater or equal to checkin date."))
            diffdate = self.checkout_date - self.checkin_date
            qty = diffdate.days
            if diffdate.total_seconds() > 0:
                qty = qty + 1
            self.duration = qty
            for line in self.room_line_ids:
                line.checkin_date = self.checkin_date
                line.checkout_date = self.checkout_date
                line.uom_qty = qty

    @api.onchange('food_order_line_ids', 'room_line_ids',
                  'service_line_ids', 'vehicle_line_ids', 'event_line_ids')
    def _onchange_room_line_ids(self):
        """Invokes the Compute amounts function"""
        self._compute_amount_untaxed()
        self.invoice_button_visible = False

    @api.constrains("room_line_ids")
    def _check_duplicate_folio_room_line(self):
        """
        This method is used to validate the room_lines.
        ------------------------------------------------
        @param self: object pointer
        @return: raise warning depending on the validation
        """
        for record in self:
            # Create a set of unique ids
            ids = set()
            for line in record.room_line_ids:
                if line.room_id.id in ids:
                    raise ValidationError(
                        (
                            """Room Entry Duplicates Found!, """
                            """You Cannot Book "%s" Room More Than Once!"""
                        )
                        % line.room_id.name
                    )
                ids.add(line.room_id.id)

    def create_list(self, line_ids):
        """Returns a Dictionary containing the Booking line Values"""
        account_move_line = self.env['account.move.line'].search_read(
            domain=[('ref', '=', self.name),
                    ('display_type', '!=', 'payment_term')],
            fields=['name', 'quantity', 'price_unit', 'product_type'], )
        for rec in account_move_line:
            del rec['id']
        booking_dict = {}
        for line in line_ids:
            name = ""
            product_type = ""
            if line_ids._name == 'food.booking.line':
                name = line.food_id.name
                product_type = 'food'
            elif line_ids._name == 'fleet.booking.line':
                name = line.fleet_id.name
                product_type = 'fleet'
            elif line_ids._name == 'service.booking.line':
                name = line.service_id.name
                product_type = 'service'
            elif line_ids._name == 'event.booking.line':
                name = line.event_id.name
                product_type = 'event'
            booking_dict = {'name': name,
                            'quantity': line.uom_qty,
                            'price_unit': line.price_unit,
                            'product_type': product_type}
        return booking_dict

    def action_reserve(self):
        """Button Reserve Function"""
        for record in self:
            if record.state == 'reserved':
                message = ("Room Already Reserved.")
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'type': 'warning',
                        'message': message,
                        'next': {'type': 'ir.actions.act_window_close'},
                    }
                }
            if record.room_line_ids:
                for room in record.room_line_ids.filtered(lambda l: l.room_id and l.room_id.exists()):
                    room.room_id.write({
                        'status': 'reserved',
                    })
                    room.room_id.is_room_avail = False
                record.write({"state": "reserved"})
            else:
                raise ValidationError(("Please Enter Room Details"))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'message': "Rooms reserved Successfully!",
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }

    def action_cancel(self):
        """
        @param self: object pointer
        """
        for record in self:
            if record.room_line_ids:
                for room in record.room_line_ids.filtered(lambda l: l.room_id and l.room_id.exists()):
                    room.room_id.write({
                        'status': 'available',
                    })
                    room.room_id.is_room_avail = True
            record.write({"state": "cancel"})

    def action_maintenance_request(self):
        """
        Function that handles the maintenance request
        """
        valid_lines = self.room_line_ids.filtered(lambda l: l.room_id and l.room_id.exists())
        if valid_lines:
            room_id = valid_lines.mapped('room_id')
            self.env['maintenance.request'].sudo().create({
                'name': 'Maintenance Request - %s' % self.name,
                'date': fields.Date.today(),
                'state': 'draft',
                'type': 'room',
                'room_maintenance_ids': [(6, 0, room_id.ids)],
                'is_hotel': True,
            })
            self.maintenance_request_sent = True
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'success',
                    'message': "Maintenance Request Sent Successfully",
                    'next': {'type': 'ir.actions.act_window_close'},
                }
            }
        raise ValidationError(("Please Enter Room Details"))

    def action_done(self):
        """Button action_confirm function"""
        for record in self:
            moves = self.env['account.move'].search([('ref', '=', record.name)])
            unpaid_moves = moves.filtered(lambda m: m.payment_state == 'not_paid')
            if unpaid_moves:
                invoice_names = ', '.join(unpaid_moves.mapped(lambda m: m.name or 'Draft'))
                raise ValidationError(('Your Invoice (%s) is Due for Payment.') % invoice_names)
            record.write({"state": "done"})
            record.is_checkin = False
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'message': "Booking Checked Out Successfully!",
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }

    def action_checkout(self):
        """Button action_heck_out function"""
        for record in self:
            record.write({"state": "check_out"})
            for room in record.room_line_ids.filtered(lambda l: l.room_id and l.room_id.exists()):
                room.room_id.write({
                    'status': 'available',
                    'is_room_avail': True
                })
                room.write({'checkout_date': datetime.today()})

    def action_invoice(self):
        """Method for creating invoice"""
        self.ensure_one()
        if not self.room_line_ids:
            raise ValidationError(("Please Enter Room Details"))
        booking_list = self._compute_amount_untaxed(True)
        if not booking_list:
            raise ValidationError((
                                      "No new items to invoice. All items appear to be already invoiced (e.g. via POS or separate invoice)."))

        account_move = self.env["account.move"].create([{
            'move_type': 'out_invoice',
            'invoice_date': fields.Date.today(),
            'partner_id': self.partner_id.id,
            'ref': self.name,
        }])
        for rec in booking_list:
            self.env['account.move.line'].create([{
                'name': rec['name'],
                'quantity': rec['quantity'],
                'price_unit': rec['price_unit'],
                'move_id': account_move.id,
                'price_subtotal': rec['quantity'] * rec['price_unit'],
                'product_type': rec['product_type'],
            }])
        self.write({'invoice_status': "invoiced"})
        self.invoice_button_visible = True
        return {
            'type': 'ir.actions.act_window',
            'name': 'Invoices',
            'view_mode': 'form',
            'res_model': 'account.move',
            'view_id': self.env.ref('account.view_move_form').id,
            'res_id': account_move.id,
            'context': "{'create': False}"
        }

    def action_view_invoices(self):
        """Method for Returning invoice View"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Invoices',
            'view_mode': 'list,form',
            'view_type': 'list,form',
            'res_model': 'account.move',
            'domain': [('ref', '=', self.name)],
            'context': "{'create': False}"
        }

    def action_checkin(self):
        """
        @param self: object pointer
        """
        for record in self:
            if not record.room_line_ids:
                raise ValidationError(("Please Enter Room Details"))
            else:
                for room in record.room_line_ids.filtered(lambda l: l.room_id and l.room_id.exists()):
                    room.room_id.write({
                        'status': 'occupied',
                    })
                    room.room_id.is_room_avail = False
                record.write({"state": "check_in"})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'message': "Booking Checked In Successfully!",
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }

    @api.model
    def get_details(self, *args, **kwargs):
        """ Returns different counts for displaying in dashboard"""
        today_date = fields.Date.context_today(self)
        
        try:
            total_room = self.env['product.template'].search_count([('is_room', '=', True)])
        except Exception:
            total_room = 0

        try:
            available_room_count = len(self.env['product.template'].search([('is_room', '=', True), ('status', '=', 'available')]))
        except Exception:
            available_room_count = 0

        try:
            check_in = self.env['room.booking'].search_count([('state', '=', 'check_in')])
        except Exception:
            check_in = 0

        try:
            reservation = self.env['room.booking'].search_count([('state', '=', 'reserved')])
        except Exception:
            reservation = 0

        check_out = 0
        try:
            check_outs = self.env['room.booking'].search([])
            for rec in check_outs:
                for room in rec.room_line_ids:
                    if room.checkout_date and fields.Date.to_date(fields.Datetime.context_timestamp(self, room.checkout_date)) == today_date:
                        check_out += 1
        except Exception:
            check_out = 0

        staff = 0
        try:
            group_xmlids = [
                'hotel_management_odoo.hotel_group_admin',
                'hotel_management_odoo.cleaning_team_group_head',
                'hotel_management_odoo.cleaning_team_group_user',
                'hotel_management_odoo.hotel_group_reception',
                'hotel_management_odoo.maintenance_team_group_leader',
                'hotel_management_odoo.maintenance_team_group_user',
            ]
            group_ids = []
            for xml_id in group_xmlids:
                group = self.env.ref(xml_id, raise_if_not_found=False)
                if group:
                    group_ids.append(group.id)
            if group_ids:
                staff = self.env['res.users'].search_count([('group_ids', 'in', group_ids)])
        except Exception:
            staff = 0

        try:
            total_vehicle = self.env['fleet.vehicle.model'].search_count([])
        except Exception:
            total_vehicle = 0

        try:
            available_vehicle = total_vehicle - self.env['fleet.booking.line'].search_count([('state', '=', 'check_in')])
        except Exception:
            available_vehicle = 0

        try:
            total_event = self.env['event.event'].search_count([])
        except Exception:
            total_event = 0

        pending_events = 0
        today_events = 0
        try:
            for pending in self.env['event.event'].search([]):
                if pending.date_end and pending.date_end >= fields.Datetime.now():
                    pending_events += 1
                if pending.date_end and fields.Date.to_date(fields.Datetime.context_timestamp(self, pending.date_end)) == today_date:
                    today_events += 1
        except Exception:
            pass

        try:
            food_items = self.env['lunch.product'].search_count([])
        except Exception:
            food_items = 0

        try:
            food_order = len(self.env['food.booking.line'].search([]).filtered(
                lambda r: r.booking_id and r.booking_id.state not in ['check_out', 'cancel', 'done']))
        except Exception:
            food_order = 0

        total_revenue = 0
        today_revenue = 0
        pending_payment = 0
        try:
            for rec in self.env['account.move'].search([('payment_state', '=', 'paid')]):
                if rec.ref and ('BOOKING' in rec.ref or 'HP/' in rec.ref):
                    total_revenue += rec.amount_total
                    if rec.date == fields.Date.today():
                        today_revenue += rec.amount_total
            for rec in self.env['account.move'].search([('payment_state', '=', 'not_paid')]):
                if rec.ref and ('BOOKING' in rec.ref or 'HP/' in rec.ref):
                    pending_payment += rec.amount_total
        except Exception:
            pass

        try:
            night_audit_count = self.env['hotel.night.audit'].search_count([])
        except Exception:
            night_audit_count = 0

        currency = self.env.company.currency_id
        return {
            'total_room': total_room,
            'available_room': available_room_count,
            'staff': staff,
            'check_in': check_in,
            'reservation': reservation,
            'check_out': check_out,
            'total_vehicle': total_vehicle,
            'available_vehicle': available_vehicle,
            'total_event': total_event,
            'today_events': today_events,
            'pending_events': pending_events,
            'night_audit': night_audit_count,
            'food_items': food_items,
            'food_order': food_order,
            'total_revenue': round(total_revenue, 2),
            'today_revenue': round(today_revenue, 2),
            'pending_payment': round(pending_payment, 2),
            'currency_symbol': currency.symbol if currency else '$',
            'currency_position': currency.position if currency else 'before'
        }

    def action_compute_bill(self):
        """Open the Compute Bill wizard"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Compute Bill',
            'res_model': 'compute.bill',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_booking_id': self.id}
        }

    def action_transfer_room(self):
        """Open the Room Transfer wizard for a checked-in booking."""
        self.ensure_one()
        current_room = self.room_line_ids.filtered(lambda l: l.room_id and l.room_id.exists())[:1].room_id
        return {
            'type': 'ir.actions.act_window',
            'name': _('Transfer Room'),
            'res_model': 'room.transfer.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_booking_id': self.id,
                'default_current_room_id': current_room.id if current_room else False,
            }
        }