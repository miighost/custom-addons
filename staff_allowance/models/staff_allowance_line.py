from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class StaffAllowanceLine(models.Model):
    """A personal override: this beneficiary, this category, this limit."""

    _name = "staff.allowance.line"
    _description = "Allowance"
    _inherit = ["staff.allowance.beneficiary.mixin"]
    _rec_name = "beneficiary_name"
    _order = "beneficiary_name, category_id"

    category_id = fields.Many2one(
        "staff.allowance.category", required=True, ondelete="cascade", index=True
    )
    company_id = fields.Many2one(
        related="category_id.company_id", store=True, readonly=True
    )

    daily_limit = fields.Integer(
        required=True, default=10,
        help="Overrides both the plan and the category default for this person.",
    )
    # Deliberately not called `active`: an `active` field would archive the row
    # and hide it from the Allowance tab.
    allowed = fields.Boolean(
        string="Allowed", default=True,
        help="Uncheck to block this person from this category entirely.",
    )

    used_today = fields.Integer(compute="_compute_usage", string="Used Today")
    remaining_today = fields.Integer(compute="_compute_usage", string="Remaining")
    status = fields.Selection(
        [("blocked", "Blocked"),
         ("ok", "Available"),
         ("near", "Almost Used Up"),
         ("reached", "Limit Reached"),
         ("over", "Over Limit")],
        compute="_compute_usage",
        string="Today",
    )
    overdraft_today = fields.Integer(compute="_compute_usage", string="Over By")
    resets_at = fields.Datetime(compute="_compute_usage")

    # ------------------------------------------------------------------
    @api.depends("employee_id", "partner_id", "category_id", "daily_limit",
                 "allowed")
    def _compute_usage(self):
        for line in self:
            beneficiary = line._beneficiary()
            if not beneficiary or not line.category_id:
                line.used_today = line.remaining_today = line.overdraft_today = 0
                line.status = False
                line.resets_at = False
                continue
            if not line.allowed:
                line.used_today = line.remaining_today = line.overdraft_today = 0
                line.status = "blocked"
                line.resets_at = line._resets_at(beneficiary)
                continue

            used = line.category_id._used_today(beneficiary)
            limit = line.daily_limit
            line.used_today = used
            line.remaining_today = max(limit - used, 0)
            line.overdraft_today = max(used - limit, 0)
            line.resets_at = line._resets_at(beneficiary)
            if used > limit:
                line.status = "over"
            elif limit and used >= limit:
                line.status = "reached"
            elif limit and used >= limit * 0.8:
                line.status = "near"
            else:
                line.status = "ok"

    # ------------------------------------------------------------------
    @api.onchange("category_id")
    def _onchange_category_id(self):
        if self.category_id:
            self.daily_limit = self.category_id.daily_limit

    @api.constrains("employee_id", "partner_id", "category_id")
    def _check_unique_category(self):
        for line in self:
            duplicate = self.search(
                self._beneficiary_domain(line._beneficiary())
                + [("category_id", "=", line.category_id.id), ("id", "!=", line.id)],
                limit=1,
            )
            if duplicate:
                raise ValidationError(
                    _("%(who)s already has an allowance line for %(category)s.",
                      who=line.beneficiary_name, category=line.category_id.name)
                )

    @api.constrains("daily_limit")
    def _check_daily_limit(self):
        for line in self:
            if line.daily_limit < 0:
                raise ValidationError(_("The daily limit cannot be negative."))

    @api.constrains("employee_id", "partner_id", "category_id")
    def _check_scope(self):
        for line in self:
            category = line.category_id
            if category.applies_to == "employee" and line.partner_id:
                raise ValidationError(
                    _("The category %s applies to employees only.", category.name)
                )
            if category.applies_to == "partner" and line.employee_id:
                raise ValidationError(
                    _("The category %s applies to contacts only.", category.name)
                )

    def _compute_display_name(self):
        for line in self:
            line.display_name = "%s / %s" % (
                line.beneficiary_name or "", line.category_id.name or ""
            )

    # ------------------------------------------------------------------
    # Keep the stored usage rows aligned when a limit is edited
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines._refresh_usage()
        return lines

    def write(self, vals):
        result = super().write(vals)
        self._refresh_usage()
        return result

    def unlink(self):
        keys = self._usage_keys()
        result = super().unlink()
        self.env["staff.allowance.usage"]._refresh_keys(keys)
        return result

    def _usage_keys(self):
        keys = set()
        for line in self:
            beneficiary = line._beneficiary()
            if beneficiary and line.category_id:
                keys.add((beneficiary._name, beneficiary.id,
                          line.category_id.id, line._local_today(beneficiary)))
        return keys

    def _refresh_usage(self):
        self.env["staff.allowance.usage"]._refresh_keys(self._usage_keys())

    # ------------------------------------------------------------------
    def action_view_today_orders(self):
        self.ensure_one()
        beneficiary = self._beneficiary()
        domain = self._beneficiary_domain(beneficiary) + [
            ("category_id", "=", self.category_id.id),
            ("order_date", "=", self._local_today(beneficiary)),
        ]
        return {
            "type": "ir.actions.act_window",
            "name": _("Today's Orders"),
            "res_model": "staff.allowance.order",
            "view_mode": "list,form",
            "domain": domain,
        }
