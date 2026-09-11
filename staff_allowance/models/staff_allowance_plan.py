from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class StaffAllowancePlan(models.Model):
    """A reusable set of category limits — the 'tier' you assign to people.

    Example: a "Staff" plan with Coffee 10 / Snacks 5, and a "Manager" plan
    with Coffee 15 / Snacks 10 / Meals 2. Assign the plan once on the employee
    or contact instead of editing every category by hand.
    """

    _name = "staff.allowance.plan"
    _description = "Allowance Plan"
    _order = "sequence, name"

    name = fields.Char(required=True, translate=True)
    code = fields.Char(copy=False)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    color = fields.Integer()
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company, required=True
    )
    note = fields.Text(string="Internal Notes")

    strict = fields.Boolean(
        string="Plan Is Exhaustive",
        default=False,
        help="If enabled, beneficiaries on this plan may ONLY order from the "
             "categories listed below. Any other category is blocked for them.",
    )

    line_ids = fields.One2many("staff.allowance.plan.line", "plan_id", copy=True)
    employee_ids = fields.One2many("hr.employee", "allowance_plan_id")
    partner_ids = fields.One2many("res.partner", "allowance_plan_id")

    employee_count = fields.Integer(compute="_compute_holder_counts")
    partner_count = fields.Integer(compute="_compute_holder_counts")

    def _compute_holder_counts(self):
        employees = self.env["hr.employee"]._read_group(
            [("allowance_plan_id", "in", self.ids)],
            groupby=["allowance_plan_id"], aggregates=["__count"],
        )
        partners = self.env["res.partner"]._read_group(
            [("allowance_plan_id", "in", self.ids)],
            groupby=["allowance_plan_id"], aggregates=["__count"],
        )
        emp_map = {plan.id: count for plan, count in employees}
        part_map = {plan.id: count for plan, count in partners}
        for plan in self:
            plan.employee_count = emp_map.get(plan.id, 0)
            plan.partner_count = part_map.get(plan.id, 0)

    @api.constrains("code")
    def _check_code_unique(self):
        for plan in self:
            if not plan.code:
                continue
            duplicate = self.with_context(active_test=False).search(
                [("code", "=", plan.code), ("id", "!=", plan.id)], limit=1
            )
            if duplicate:
                raise ValidationError(
                    _("The plan code %s is already used.", plan.code)
                )

    def action_view_employees(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Employees on %s", self.name),
            "res_model": "hr.employee",
            "view_mode": "kanban,list,form",
            "domain": [("allowance_plan_id", "=", self.id)],
        }

    def action_view_partners(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Contacts on %s", self.name),
            "res_model": "res.partner",
            "view_mode": "kanban,list,form",
            "domain": [("allowance_plan_id", "=", self.id)],
        }


class StaffAllowancePlanLine(models.Model):
    _name = "staff.allowance.plan.line"
    _description = "Allowance Plan Line"
    _order = "plan_id, category_id"

    plan_id = fields.Many2one(
        "staff.allowance.plan", required=True, ondelete="cascade", index=True
    )
    category_id = fields.Many2one(
        "staff.allowance.category", required=True, ondelete="cascade", index=True
    )
    unlimited = fields.Boolean(
        string="No Limit",
        help="Everyone on this plan orders freely in this category.",
    )
    daily_limit = fields.Integer(required=True, default=10)
    category_default = fields.Integer(
        related="category_id.daily_limit", string="Category Default", readonly=True
    )

    @api.onchange("category_id")
    def _onchange_category_id(self):
        if self.category_id:
            self.daily_limit = self.category_id.daily_limit

    @api.constrains("plan_id", "category_id")
    def _check_unique_category(self):
        for line in self:
            duplicate = self.search([
                ("plan_id", "=", line.plan_id.id),
                ("category_id", "=", line.category_id.id),
                ("id", "!=", line.id),
            ], limit=1)
            if duplicate:
                raise ValidationError(
                    _("%(category)s is listed twice in the plan %(plan)s.",
                      category=line.category_id.name, plan=line.plan_id.name)
                )

    @api.constrains("daily_limit")
    def _check_daily_limit(self):
        for line in self:
            if line.daily_limit < 0:
                raise ValidationError(_("The daily limit cannot be negative."))
