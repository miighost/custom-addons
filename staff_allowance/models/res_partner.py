from odoo import _, fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    allowance_plan_id = fields.Many2one(
        "staff.allowance.plan", string="Allowance Plan",
        help="Tier of daily limits applied to this contact. Personal lines "
             "override it.",
    )
    allowance_line_ids = fields.One2many(
        "staff.allowance.line", "partner_id", string="Allowances"
    )
    allowance_order_ids = fields.One2many(
        "staff.allowance.order", "partner_id", string="Allowance Orders"
    )
    allowance_order_count = fields.Integer(compute="_compute_allowance_counts")
    allowance_over_count = fields.Integer(compute="_compute_allowance_counts")

    def _compute_allowance_counts(self):
        Order = self.env["staff.allowance.order"].sudo()
        done = Order._read_group(
            [("partner_id", "in", self.ids), ("state", "in", ("draft", "done"))],
            groupby=["partner_id"], aggregates=["__count"],
        )
        over = Order._read_group(
            [("partner_id", "in", self.ids), ("is_over_limit", "=", True),
             ("state", "in", ("draft", "done"))],
            groupby=["partner_id"], aggregates=["__count"],
        )
        done_map = {p.id: c for p, c in done}
        over_map = {p.id: c for p, c in over}
        for partner in self:
            partner.allowance_order_count = done_map.get(partner.id, 0)
            partner.allowance_over_count = over_map.get(partner.id, 0)

    def action_view_allowance_orders(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Allowance Orders"),
            "res_model": "staff.allowance.order",
            "view_mode": "list,pivot,form",
            "domain": [("partner_id", "=", self.id)],
            "context": {"default_partner_id": self.id},
        }

    def action_apply_allowance_plan(self):
        Line = self.env["staff.allowance.line"]
        for partner in self:
            if not partner.allowance_plan_id:
                continue
            existing = partner.allowance_line_ids.mapped("category_id")
            for plan_line in partner.allowance_plan_id.line_ids:
                if plan_line.category_id in existing:
                    continue
                Line.create({
                    "partner_id": partner.id,
                    "category_id": plan_line.category_id.id,
                    "unlimited": plan_line.unlimited,
                    "daily_limit": plan_line.daily_limit,
                })
