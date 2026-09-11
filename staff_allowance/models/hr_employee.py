from odoo import _, api, fields, models


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    allowance_plan_id = fields.Many2one(
        "staff.allowance.plan", string="Allowance Plan",
        help="Tier of daily limits applied to this employee. Personal lines "
             "below override it.",
    )
    allowance_line_ids = fields.One2many(
        "staff.allowance.line", "employee_id", string="Allowances"
    )
    allowance_order_ids = fields.One2many(
        "staff.allowance.order", "employee_id", string="Allowance Orders"
    )
    allowance_order_count = fields.Integer(compute="_compute_allowance_counts")
    allowance_over_count = fields.Integer(compute="_compute_allowance_counts")

    def _compute_allowance_counts(self):
        Order = self.env["staff.allowance.order"].sudo()
        done = Order._read_group(
            [("employee_id", "in", self.ids), ("state", "in", ("draft", "done"))],
            groupby=["employee_id"], aggregates=["__count"],
        )
        over = Order._read_group(
            [("employee_id", "in", self.ids), ("is_over_limit", "=", True),
             ("state", "in", ("draft", "done"))],
            groupby=["employee_id"], aggregates=["__count"],
        )
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
        """Materialise the assigned plan as personal lines, so they can be tuned."""
        Line = self.env["staff.allowance.line"]
        for employee in self:
            if not employee.allowance_plan_id:
                continue
            existing = employee.allowance_line_ids.mapped("category_id")
            for plan_line in employee.allowance_plan_id.line_ids:
                if plan_line.category_id in existing:
                    continue
                Line.create({
                    "employee_id": employee.id,
                    "category_id": plan_line.category_id.id,
                    "unlimited": plan_line.unlimited,
                    "daily_limit": plan_line.daily_limit,
                })

    def action_add_missing_allowances(self):
        """Add a line for every category this employee has none for."""
        Category = self.env["staff.allowance.category"]
        Line = self.env["staff.allowance.line"]
        categories = Category.search([("applies_to", "in", ("all", "employee"))])
        for employee in self:
            missing = categories - employee.allowance_line_ids.mapped("category_id")
            for category in missing:
                allowed, unlimited, limit, _origin = category._limit_for(employee)
                Line.create({
                    "employee_id": employee.id,
                    "category_id": category.id,
                    "unlimited": unlimited,
                    "daily_limit": limit or category.daily_limit,
                    "allowed": allowed,
                })
