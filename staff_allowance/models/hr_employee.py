from odoo import _, fields, models


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    allowance_plan_id = fields.Many2one(
        "staff.allowance.plan", string="Allowance Plan",
        help="Tier of rules applied to this employee. Personal rules below "
             "override it. Categories in neither stay free.")
    allowance_rule_ids = fields.One2many("staff.allowance.rule", "employee_id",
                                         string="Allowance Rules")
    allowance_order_count = fields.Integer(compute="_compute_allowance_counts")
    allowance_over_count = fields.Integer(compute="_compute_allowance_counts")

    def _compute_allowance_counts(self):
        Order = self.env["staff.allowance.order"].sudo()
        done = Order._read_group(
            [("employee_id", "in", self.ids), ("state", "in", ("draft", "done"))],
            groupby=["employee_id"], aggregates=["__count"])
        over = Order._read_group(
            [("employee_id", "in", self.ids), ("is_over_limit", "=", True),
             ("state", "in", ("draft", "done"))],
            groupby=["employee_id"], aggregates=["__count"])
        done_map = {e.id: c for e, c in done}
        over_map = {e.id: c for e, c in over}
        for employee in self:
            employee.allowance_order_count = done_map.get(employee.id, 0)
            employee.allowance_over_count = over_map.get(employee.id, 0)

    def action_view_allowance_orders(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Allowance Orders"),
            "res_model": "staff.allowance.order",
            "view_mode": "list,pivot,form",
            "domain": [("employee_id", "=", self.id)],
            "context": {"default_employee_id": self.id},
        }

    def action_apply_allowance_plan(self):
        """Copy the plan into personal rules, so they can be tuned."""
        Rule = self.env["staff.allowance.rule"]
        for employee in self:
            if not employee.allowance_plan_id:
                continue
            existing = employee.allowance_rule_ids.mapped("pos_category_id")
            for line in employee.allowance_plan_id.line_ids:
                if line.pos_category_id in existing:
                    continue
                Rule.create({
                    "employee_id": employee.id,
                    "pos_category_id": line.pos_category_id.id,
                    "daily_limit": line.daily_limit,
                    "count_mode": line.count_mode,
                    "policy": line.policy,
                    "tolerance": line.tolerance,
                })
