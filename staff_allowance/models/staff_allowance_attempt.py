import pytz

from odoo import api, fields, models


class StaffAllowanceAttempt(models.Model):
    """Every refused order, kept so you can see who is hitting their limit.

    Orders that go through are in `staff.allowance.order`. Orders that were
    refused leave no order row at all — they land here instead, which is what
    makes the "who ran out of coffee today?" report possible.
    """

    _name = "staff.allowance.attempt"
    _description = "Blocked Allowance Attempt"
    _inherit = ["staff.allowance.beneficiary.mixin"]
    _rec_name = "beneficiary_name"
    _order = "attempt_datetime desc, id desc"

    category_id = fields.Many2one(
        "staff.allowance.category", required=True, index=True, ondelete="cascade"
    )
    product_id = fields.Many2one("product.product", ondelete="set null")
    qty = fields.Integer(default=1, string="Requested Qty")

    attempt_datetime = fields.Datetime(
        default=fields.Datetime.now, required=True, index=True
    )
    attempt_date = fields.Date(
        compute="_compute_attempt_date", store=True, index=True, string="Day"
    )

    reason = fields.Selection(
        [("limit_reached", "Daily Limit Reached"),
         ("overdraft_exceeded", "Over-Limit Tolerance Used Up"),
         ("not_allowed", "Not Allowed in This Category"),
         ("product_not_allowed", "Product Not Allowed"),
         ("bad_qty", "Invalid Quantity")],
        required=True, index=True,
    )
    message = fields.Char(string="Message Sent Back")
    source = fields.Selection(
        [("app", "Mobile App"), ("backend", "Backend"), ("pos", "Point of Sale")],
        default="app", required=True,
    )

    limit_at_attempt = fields.Integer(string="Limit")
    used_at_attempt = fields.Integer(string="Already Used")
    company_id = fields.Many2one(
        related="category_id.company_id", store=True, readonly=True
    )

    @api.depends("attempt_datetime", "employee_id", "partner_id")
    def _compute_attempt_date(self):
        for attempt in self:
            beneficiary = attempt._beneficiary()
            if not attempt.attempt_datetime or not beneficiary:
                attempt.attempt_date = False
                continue
            tz = attempt._beneficiary_tz(beneficiary)
            attempt.attempt_date = (
                pytz.utc.localize(attempt.attempt_datetime).astimezone(tz).date()
            )

    def _compute_display_name(self):
        for attempt in self:
            attempt.display_name = "%s - %s" % (
                attempt.beneficiary_name or "", attempt.category_id.name or ""
            )
