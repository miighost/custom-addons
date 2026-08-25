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
#############################################################################
import io
import json
from datetime import datetime, time
from odoo import api, fields, models
from odoo.tools import json_default

try:
    from odoo.tools.misc import xlsxwriter
except ImportError:
    import xlsxwriter


class HotelNightAudit(models.Model):
    """Model to store, manage, and print Daily Hotel Night Audits."""

    _name = "hotel.night.audit"
    _description = "Hotel Night Audit"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date desc, id desc"

    name = fields.Char(
        string="Audit Reference",
        compute="_compute_name",
        store=True,
        tracking=True,
        help="Reference title for the night audit record"
    )
    date = fields.Date(
        string="Audit Date",
        default=fields.Date.context_today,
        required=True,
        tracking=True,
        help="The 24-hour audit date"
    )
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        default=lambda self: self.env.company,
        required=True
    )
    currency_id = fields.Many2one(
        "res.currency",
        related="company_id.currency_id",
        string="Currency"
    )
    user_id = fields.Many2one(
        "res.users",
        string="Audited / Printed By",
        default=lambda self: self.env.user,
        required=True,
        tracking=True
    )
    state = fields.Selection([
        ("draft", "Draft"),
        ("closed", "Audited / Closed"),
    ], default="draft", string="Status", tracking=True)

    # 24-Hour Key Performance Indicators (Computed)
    check_ins_count = fields.Integer(
        string="Check-Ins",
        compute="_compute_kpis",
        help="Number of arrivals on this audit date"
    )
    check_outs_count = fields.Integer(
        string="Check-Outs",
        compute="_compute_kpis",
        help="Number of departures on this audit date"
    )
    in_house_guests_count = fields.Integer(
        string="In-House Guests",
        compute="_compute_kpis",
        help="Total staying in-house guests / rooms"
    )
    daily_room_rent = fields.Monetary(
        string="Daily Room Rent",
        compute="_compute_kpis",
        currency_field="currency_id",
        help="Total room rent accrued on this audit date"
    )
    daily_pos_revenue = fields.Monetary(
        string="Daily POS / Rest Revenue",
        compute="_compute_kpis",
        currency_field="currency_id",
        help="Total POS and restaurant revenue on this audit date"
    )
    total_day_revenue = fields.Monetary(
        string="Total Day Revenue",
        compute="_compute_kpis",
        currency_field="currency_id",
        help="Combined 24-hour revenue (Room Rent + Restaurant/POS)"
    )
    notes = fields.Text(string="Audit Notes / Handover Remarks")

    @api.depends("date")
    def _compute_name(self):
        """Compute human-friendly Audit Reference name."""
        for rec in self:
            if rec.date:
                rec.name = f"Night Audit - {rec.date.strftime('%Y-%m-%d')}"
            else:
                rec.name = "Night Audit"

    @api.depends("date", "company_id")
    def _compute_kpis(self):
        """Compute real-time 24-hour KPIs for the chosen audit date."""
        for rec in self:
            if not rec.date:
                rec.check_ins_count = 0
                rec.check_outs_count = 0
                rec.in_house_guests_count = 0
                rec.daily_room_rent = 0.0
                rec.daily_pos_revenue = 0.0
                rec.total_day_revenue = 0.0
                continue

            target_date = rec.date
            dt_start = datetime.combine(target_date, time.min)
            dt_end = datetime.combine(target_date, time.max)

            # 1. Check-Ins today
            rec.check_ins_count = self.env["room.booking"].search_count([
                ("checkin_date", ">=", dt_start),
                ("checkin_date", "<=", dt_end),
                ("state", "in", ["check_in", "reserved", "check_out", "done"]),
            ])

            # 2. Check-Outs today
            rec.check_outs_count = self.env["room.booking"].search_count([
                ("checkout_date", ">=", dt_start),
                ("checkout_date", "<=", dt_end),
                ("state", "in", ["check_out", "done", "check_in"]),
            ])

            # 3. In-house active bookings & daily room rent
            active_bookings = self.env["room.booking"].search([
                ("checkin_date", "<=", dt_end),
                ("checkout_date", ">=", dt_start),
                ("state", "in", ["check_in", "reserved", "check_out", "done"]),
            ])

            inhouse_b_count = self.env["room.booking"].search_count([
                ("state", "=", "check_in"),
            ])
            rec.in_house_guests_count = inhouse_b_count

            total_room_rent = 0.0
            for b in active_bookings:
                for rline in b.room_line_ids:
                    r_in = rline.checkin_date or b.checkin_date
                    r_out = rline.checkout_date or b.checkout_date
                    if r_in and r_in > dt_end:
                        continue
                    if r_out and r_out < dt_start:
                        continue
                    rent = rline.price_unit if rline.price_unit else (
                        rline.price_subtotal / (b.duration or 1) if b.duration else rline.price_subtotal
                    )
                    total_room_rent += rent
            rec.daily_room_rent = total_room_rent

            # 4. POS / Restaurant revenue
            total_pos = 0.0
            if "pos.order" in self.env:
                pos_orders = self.env["pos.order"].search([
                    ("date_order", ">=", dt_start),
                    ("date_order", "<=", dt_end),
                    ("state", "in", ["paid", "done", "invoiced"]),
                ])
                total_pos += sum(pos_orders.mapped("amount_total"))

            food_lines = self.env["food.booking.line"].search([
                ("booking_id.checkin_date", "<=", dt_end),
                ("booking_id.checkout_date", ">=", dt_start),
            ])
            total_pos += sum(food_lines.mapped("price_total"))
            rec.daily_pos_revenue = total_pos

            # 5. Grand Total Day Revenue
            rec.total_day_revenue = total_room_rent + total_pos

    def action_close_audit(self):
        """Mark night audit as audited and closed."""
        self.ensure_one()
        self.write({"state": "closed"})
        self.message_post(body=f"<b>Night Audit Closed:</b> Completed on {fields.Datetime.now().strftime('%d/%m/%Y %H:%M')}")

    def action_reopen(self):
        """Re-open night audit to draft."""
        self.ensure_one()
        self.write({"state": "draft"})
        self.message_post(body="<b>Night Audit Re-Opened to Draft.</b>")

    def generate_night_audit_data(self):
        """Consolidate full operational & financial dataset for printing the 5-in-1 Audit Pack."""
        self.ensure_one()
        # Use wizard data builder logic
        wizard = self.env["night.audit.wizard"].new({
            "date": self.date,
            "user_id": self.user_id.id,
            "notes": self.notes,
        })
        return wizard.generate_night_audit_data()

    def action_print_pdf(self):
        """Generate and download the 5-in-1 PDF Audit Pack."""
        self.ensure_one()
        data = {
            "audit_data": self.generate_night_audit_data(),
        }
        return self.env.ref("hotel_management_odoo.action_report_night_audit").report_action(self, data=data)

    def action_print_excel(self):
        """Generate Multi-Tab Excel Workbook."""
        self.ensure_one()
        data = {
            "audit_data": self.generate_night_audit_data(),
        }
        return {
            "type": "ir.actions.report",
            "data": {
                "model": "night.audit.wizard",
                "options": json.dumps(data, default=json_default),
                "output_format": "xlsx",
                "report_name": f"Night Audit Pack - {self.date.strftime('%d-%b-%Y')}",
            },
            "report_type": "xlsx",
        }
