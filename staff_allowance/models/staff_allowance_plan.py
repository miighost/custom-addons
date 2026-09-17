from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class StaffAllowancePlan(models.Model):
    """A reusable set of rules — assign one tier to many people.

    A plan only covers the categories listed in it. Anything else stays free,
    exactly as if the person had no plan at all.
    """

    _name = "staff.allowance.plan"
    _description = "Allowance Plan"
    _order = "sequence, name"

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    line_ids = fields.One2many("staff.allowance.plan.line", "plan_id", copy=True)
    # Plans are set on contacts, and staff are contacts too (their work
    # contact), so one count covers everybody on the plan.
    partner_count = fields.Integer(string="People", compute="_compute_partner_count")

    def _compute_partner_count(self):
        counts = dict(self.env["res.partner"]._read_group(
            [("allowance_plan_id", "in", self.ids)],
            groupby=["allowance_plan_id"], aggregates=["__count"]))
        for plan in self:
            plan.partner_count = counts.get(plan, 0)

    def action_view_partners(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("People on %s", self.name),
            "res_model": "res.partner",
            "view_mode": "list,form",
            "domain": [("allowance_plan_id", "=", self.id)],
        }


class StaffAllowancePlanLine(models.Model):
    _name = "staff.allowance.plan.line"
    _description = "Allowance Plan Line"
    _order = "plan_id, pos_category_id"

    plan_id = fields.Many2one("staff.allowance.plan", required=True,
                              ondelete="cascade", index=True)
    pos_category_id = fields.Many2one("pos.category", string="POS Category",
                                      required=True, ondelete="cascade",
                                      index=True)
    daily_limit = fields.Integer(required=True, default=10)
    count_mode = fields.Selection(
        [("qty", "Units ordered"), ("order", "Number of orders")],
        default="qty", required=True)
    policy = fields.Selection(
        [("block", "Block the order"),
         ("approval", "Allow, but require approval"),
         ("allow", "Allow and flag as over limit")],
        string="At the Limit", default="block", required=True)
    tolerance = fields.Integer(default=0)

    @api.constrains("plan_id", "pos_category_id")
    def _check_unique_category(self):
        for line in self:
            duplicate = self.search([
                ("plan_id", "=", line.plan_id.id),
                ("pos_category_id", "=", line.pos_category_id.id),
                ("id", "!=", line.id),
            ], limit=1)
            if duplicate:
                raise ValidationError(
                    _("%(category)s is listed twice in the plan %(plan)s.",
                      category=line.pos_category_id.display_name,
                      plan=line.plan_id.name))

    @api.constrains("daily_limit", "tolerance")
    def _check_limits(self):
        for line in self:
            if line.daily_limit < 0 or line.tolerance < 0:
                raise ValidationError(_("Limits cannot be negative."))
