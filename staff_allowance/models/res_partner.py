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
    allowance_summary = fields.Char(
        string="Limits", compute="_compute_allowance_today",
        help="The daily limits in force, personal rules first, e.g. "
             "\"Coffee 2/day · Food 1/day\".")
    allowance_status = fields.Selection(
        [("none", "Nothing Used"),
         ("ok", "Available"),
         ("near", "Almost Used Up"),
         ("reached", "Limit Reached"),
         ("over", "Over Limit")],
        string="Today", compute="_compute_allowance_today",
        help="The most used-up of this person's limits today.")

    def _compute_allowance_today(self):
        Rule = self.env["staff.allowance.rule"].sudo()
        Usage = self.env["staff.allowance.usage"].sudo()
        rules = Rule.search([("partner_id", "in", self.ids)])
        rank = {"free": 0, "ok": 1, "near": 2, "reached": 3, "over": 4}

        # One usage search per local day (usually just one for everybody).
        by_day = {}
        for partner in self:
            by_day.setdefault(Usage._local_today(partner), []).append(partner.id)
        worst = {}
        for day, partner_ids in by_day.items():
            for usage in Usage.search([("partner_id", "in", partner_ids),
                                       ("day", "=", day)]):
                current = worst.get(usage.partner_id.id, "free")
                if rank[usage.status] > rank[current]:
                    worst[usage.partner_id.id] = usage.status

        for partner in self:
            personal = rules.filtered(lambda r: r.partner_id == partner)
            parts = [f"{r.pos_category_id.name} {r.daily_limit}/day" for r in personal]
            if partner.allowance_plan_id.active:
                parts += [
                    f"{line.pos_category_id.name} {line.daily_limit}/day"
                    for line in partner.allowance_plan_id.line_ids
                    if line.pos_category_id not in personal.pos_category_id]
            partner.allowance_summary = " · ".join(parts)
            status = worst.get(partner.id, "free")
            partner.allowance_status = "none" if status == "free" else status

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

    def action_give_allowance(self):
        """Open Give an Allowance for this person: the one way to change limits."""
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "staff_allowance.action_allowance_give")
        action["context"] = {"default_partner_id": self.id}
        return action
