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
from openpyxl.worksheet import related

from odoo import api, fields, models, tools
from odoo.exceptions import ValidationError


class RoomBookingLine(models.Model):
    """Model that handles the room booking form"""
    _name = "room.booking.line"
    _description = "Hotel Folio Line"
    _rec_name = 'room_id'

    @tools.ormcache()
    def _set_default_uom_id(self):
        return self.env.ref('uom.product_uom_day')

    booking_id = fields.Many2one("room.booking", string="Booking",
                                 help="Indicates the Room",
                                 ondelete="cascade")
    checkin_date = fields.Datetime(string="Check In",
                                   help="You can choose the date,"
                                        " Otherwise sets to current Date",
                                   required=True)
    checkout_date = fields.Datetime(string="Check Out",
                                    help="You can choose the date,"
                                         " Otherwise sets to current Date",
                                    required=True)
    room_id = fields.Many2one('product.template', string="Room",
                              domain=[('status', '=', 'available')],
                              help="Indicates the Room",
                              required=True)
    uom_qty = fields.Float(string="Duration",
                           help="The quantity converted into the UoM used by "
                                "the product", readonly=True)
    uom_id = fields.Many2one('uom.uom',
                             default=_set_default_uom_id,
                             string="Unit of Measure",
                             help="This will set the unit of measure used",
                             readonly=True)
    price_unit = fields.Float(string='Rent', digits='Product Price',
                              compute='_compute_price_unit', store=True,
                              readonly=False, precompute=True,
                              help="The rent price of the selected room.")
    tax_ids = fields.Many2many('account.tax',
                               'hotel_room_order_line_taxes_rel',
                               'room_id', 'tax_id',
                               related='room_id.taxes_id',
                               string='Taxes',
                               help="Default taxes used when selling the room."
                               , domain=[('type_tax_use', '=', 'sale')])
    currency_id = fields.Many2one(string='Currency',
                                  related='booking_id.pricelist_id.currency_id'
                                  , help='The currency used')
    price_subtotal = fields.Float(string="Subtotal",
                                  compute='_compute_price_subtotal',
                                  help="Total Price excluding Tax",
                                  store=True)
    price_tax = fields.Float(string="Total Tax",
                             compute='_compute_price_subtotal',
                             help="Tax Amount",
                             store=True)
    price_total = fields.Float(string="Total",
                               compute='_compute_price_subtotal',
                               help="Total Price including Tax",
                               store=True)
    state = fields.Selection(related='booking_id.state',
                             string="Order Status",
                             help=" Status of the Order",
                             copy=False)
    booking_line_visible = fields.Boolean(default=False,
                                          string="Booking Line Visible",
                                          help="If True, then Booking Line "
                                               "will be visible")
    days_stayed = fields.Float(string="Days Stayed", compute="_compute_todays_balance", store=False,
                               help="The number of days/nights stayed up to today.")
    todays_balance = fields.Float(string="Today's Balance", compute="_compute_todays_balance", store=False,
                                  help="The accrued room charge for the days stayed so far.")

    @api.depends('checkin_date', 'checkout_date', 'uom_qty', 'price_total', 'price_unit', 'booking_id.state')
    def _compute_todays_balance(self):
        """Compute the days elapsed to date and the corresponding accrued room balance."""
        now_dt = fields.Datetime.now()
        for line in self:
            if not line.checkin_date or line.booking_id.state in ['draft', 'cancel']:
                line.days_stayed = 0.0
                line.todays_balance = 0.0
                continue

            effective_end = min(now_dt, line.checkout_date) if line.checkout_date else now_dt
            if effective_end > line.checkin_date:
                diff = effective_end - line.checkin_date
                days = diff.days
                if diff.total_seconds() > 0:
                    days += 1
                days_stayed = min(max(1.0, float(days)), line.uom_qty if line.uom_qty > 0 else float(days))
            else:
                days_stayed = 1.0

            line.days_stayed = days_stayed
            if line.uom_qty and line.uom_qty > 0:
                line.todays_balance = round((line.price_total / line.uom_qty) * days_stayed, 2)
            else:
                line.todays_balance = round(line.price_unit * days_stayed, 2)

    @api.depends('room_id', 'booking_id.pricelist_id', 'uom_qty')
    def _compute_price_unit(self):
        """Compute the rent using the booking's pricelist, falling back to
        the room's list price when there is no pricelist."""
        for line in self:
            if not line.room_id or not line.room_id.exists():
                line.price_unit = 0
                continue
            pricelist = line.booking_id.pricelist_id
            if pricelist:
                line.price_unit = pricelist._get_product_price(
                    line.room_id, line.uom_qty or 1.0)
            else:
                line.price_unit = line.room_id.list_price

    @api.onchange("checkin_date", "checkout_date")
    def _onchange_checkin_date(self):
        """When you change checkin_date or checkout_date it will check
        and update the qty of hotel service line
        -----------------------------------------------------------------
        @param self: object pointer"""
        if self.checkout_date < self.checkin_date:
            raise ValidationError(
                _("Checkout must be greater or equal checkin date"))
        if self.checkin_date and self.checkout_date:
            diffdate = self.checkout_date - self.checkin_date
            qty = diffdate.days
            if diffdate.total_seconds() > 0:
                qty = qty + 1
            self.uom_qty = qty

    @api.depends('uom_qty', 'price_unit', 'tax_ids')
    def _compute_price_subtotal(self):
        """Compute the amounts of the room booking line."""
        for line in self:
            base_line = line._prepare_base_line_for_taxes_computation()
            self.env['account.tax']._add_tax_details_in_base_line(base_line, self.env.company)
            self.env['account.tax']._round_base_lines_tax_details([base_line], self.env.company)
            line.price_subtotal = base_line['tax_details']['total_excluded_currency']
            line.price_total = base_line['tax_details']['total_included_currency']
            line.price_tax = line.price_total - line.price_subtotal
            if self.env.context.get('import_file',
                                    False) and not self.env.user. \
                    user_has_groups('account.group_account_manager'):
                line.tax_ids.invalidate_recordset(
                    ['invoice_repartition_line_ids'])

    def _prepare_base_line_for_taxes_computation(self):
        """ Convert the current record to a dictionary in order to use the generic taxes computation method
        defined on account.tax.

        :return: A python dictionary.
        """
        self.ensure_one()
        return self.env['account.tax']._prepare_base_line_for_taxes_computation(
            self,
            **{
                'tax_ids': self.tax_ids,
                'quantity': self.uom_qty,
                'partner_id': self.booking_id.partner_id,
                'currency_id': self.currency_id or self.env.company.currency_id,
            },
        )

