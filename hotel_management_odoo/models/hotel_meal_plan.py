# -*- coding: utf-8 -*-
#############################################################################
#
#    Hotel Management Odoo
#    5-Star Luxury Meal Plan Management
#
#############################################################################
from odoo import api, fields, models, _


class HotelMealPlan(models.Model):
    """Model that handles luxury 5-star hotel meal plans."""
    _name = "hotel.meal.plan"
    _description = "Hotel Meal Plan"
    _order = "sequence, id"

    name = fields.Char(
        string="Plan Name",
        required=True,
        translate=True,
        help="Full name of the meal plan (e.g. Bed & Breakfast, Ultra All Inclusive)"
    )
    code = fields.Char(
        string="Plan Code",
        required=True,
        size=10,
        help="Short standard code (e.g. BB, HB, FB, RO, AI, UAI, CP)"
    )
    sequence = fields.Integer(
        string="Sequence",
        default=10,
        help="Display ordering in lists and booking selection"
    )
    active = fields.Boolean(
        string="Active",
        default=True,
        help="Set to False to archive this meal plan"
    )
    currency_id = fields.Many2one(
        'res.currency',
        string="Currency",
        default=lambda self: self.env.company.currency_id
    )
    price = fields.Monetary(
        string="Daily Surcharge / Person",
        currency_field='currency_id',
        default=0.0,
        help="Optional surcharge per guest / per day for this meal plan"
    )

    # 5-Star Meal Inclusions
    include_breakfast = fields.Boolean(
        string="Breakfast Included",
        default=True,
        help="Includes gourmet breakfast buffet / à la carte"
    )
    include_lunch = fields.Boolean(
        string="Lunch Included",
        default=False,
        help="Includes midday lunch dining"
    )
    include_dinner = fields.Boolean(
        string="Dinner Included",
        default=False,
        help="Includes evening dinner dining"
    )
    include_snacks = fields.Boolean(
        string="Afternoon Tea / Snacks",
        default=False,
        help="Includes high tea, executive lounge access, or poolside snacks"
    )
    include_beverages = fields.Boolean(
        string="Beverages / Open Bar",
        default=False,
        help="Includes unlimited non-alcoholic or premium alcoholic beverages"
    )

    # Dining Style & Service Hours
    dining_type = fields.Selection([
        ('buffet', 'Luxury Buffet'),
        ('a_la_carte', 'Gourmet À La Carte'),
        ('fine_dining', 'Fine Dining / Chef Set Menu'),
        ('all_venues', 'All Outlets & In-Room Dining'),
    ], string="Dining Style", default='buffet', help="Primary service style for meals")

    breakfast_timing = fields.Char(string="Breakfast Hours", default="06:30 AM - 10:30 AM")
    lunch_timing = fields.Char(string="Lunch Hours", default="12:30 PM - 03:30 PM")
    dinner_timing = fields.Char(string="Dinner Hours", default="07:00 PM - 11:00 PM")
    serving_venue = fields.Char(
        string="Designated Restaurant / Venue",
        default="Main Restaurant & Garden Terrace",
        help="Restaurant or venue where this meal plan is served"
    )

    description = fields.Html(
        string="Inclusions & Terms",
        help="Detailed gourmet package description, inclusions, and terms for guests"
    )
    booking_count = fields.Integer(
        string="Reservations",
        compute="_compute_booking_count"
    )

    _sql_constraints = [
        ('code_unique', 'unique(code)', 'The meal plan code must be unique!'),
    ]

    @api.depends('name', 'code')
    def _compute_display_name(self):
        for rec in self:
            if rec.code:
                rec.display_name = f"[{rec.code}] {rec.name}"
            else:
                rec.display_name = rec.name

    def _compute_booking_count(self):
        for plan in self:
            plan.booking_count = self.env['room.booking'].search_count([('meal_plan_id', '=', plan.id)])

    def action_view_bookings(self):
        self.ensure_one()
        return {
            'name': _("Bookings: %s", self.name),
            'type': 'ir.actions.act_window',
            'res_model': 'room.booking',
            'view_mode': 'list,form',
            'domain': [('meal_plan_id', '=', self.id)],
            'context': {'default_meal_plan_id': self.id},
        }
