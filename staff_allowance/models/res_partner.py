from odoo import _, fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    allowance_plan_id = fields.Many2one(
        "staff.allowance.plan", string="Allowance Plan",
        help="Tier of rules applied to this contact. Personal rules below "
             "override it. Categories in neither stay free.")
    allowance_rule_ids = fields.One2many("staff.allowance.rule", "partner_id",
                                         string="Allowance Rules")
    allowance_order_count = fields.Integer(compute="_compute_allowance_counts")
    allowance_over_count = fields.Integer(compute="_compute_allowance_counts")

    def _compute_allowance_counts(self):
        Order = self.env["staff.allowance.order"].sudo()
        done = Order._read_group(
            [("partner_id", "in", self.ids), ("state", "in", ("draft", "done"))],
            groupby=["partner_id"], aggregates=["__count"])
        over = Order._read_group(
            [("partner_id", "in", self.ids), ("is_over_limit", "=", True),
             ("state", "in", ("draft", "done"))],
            groupby=["partner_id"], aggregates=["__count"])
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
        Rule = self.env["staff.allowance.rule"]
        for partner in self:
            if not partner.allowance_plan_id:
                continue
            existing = partner.allowance_rule_ids.mapped("pos_category_id")
            for line in partner.allowance_plan_id.line_ids:
                if line.pos_category_id in existing:
                    continue
                Rule.create({
                    "partner_id": partner.id,
                    "pos_category_id": line.pos_category_id.id,
                    "daily_limit": line.daily_limit,
                    "count_mode": line.count_mode,
                    "policy": line.policy,
                    "tolerance": line.tolerance,
                })
