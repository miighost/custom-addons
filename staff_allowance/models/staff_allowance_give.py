from odoo import _, api, fields, models
from odoo.exceptions import UserError


def _policy_selection(model):
    return model.env["staff.allowance.rule"]._fields["policy"].selection


class StaffAllowanceGive(models.TransientModel):
    """Give someone an allowance, or change theirs, in one step.

    Opens with what the person already has; saving sets their plan and makes
    their personal rules match the list. The plan is written in sudo: HR
    officers manage allowances without necessarily having rights to edit
    contacts.
    """

    _name = "staff.allowance.give"
    _description = "Give an Allowance"

    partner_id = fields.Many2one("res.partner", string="Person", required=True)
    plan_id = fields.Many2one("staff.allowance.plan", string="Plan")
    line_ids = fields.One2many("staff.allowance.give.line", "wizard_id",
                               string="Personal Limits")

    @api.onchange("partner_id")
    def _onchange_partner_id(self):
        """Start from what the person already has."""
        partner = self.partner_id
        self.plan_id = partner.allowance_plan_id
        self.line_ids = [(5, 0, 0)] + [(0, 0, {
            "pos_category_id": rule.pos_category_id.id,
            "daily_limit": rule.daily_limit,
            "policy": rule.policy,
            "tolerance": rule.tolerance,
        }) for rule in partner.allowance_rule_ids]

    def action_give(self):
        self.ensure_one()
        if not self.plan_id and not self.line_ids:
            raise UserError(_("Choose a plan, or add at least one personal limit."))
        partner = self.partner_id
        partner.sudo().allowance_plan_id = self.plan_id

        Rule = self.env["staff.allowance.rule"]
        existing = Rule.with_context(active_test=False).search(
            [("partner_id", "=", partner.id)])
        kept = Rule
        for line in self.line_ids:
            vals = {"daily_limit": line.daily_limit, "policy": line.policy,
                    "tolerance": line.tolerance, "active": True}
            rule = existing.filtered(
                lambda r: r.pos_category_id == line.pos_category_id)[:1]
            if rule:
                rule.write(vals)
            else:
                rule = Rule.create({"partner_id": partner.id,
                                    "pos_category_id": line.pos_category_id.id,
                                    **vals})
            kept |= rule
        # Limits taken off the list are archived rather than deleted, so the
        # history they belong to stays readable.
        (existing.filtered("active") - kept).write({"active": False})
        return {"type": "ir.actions.act_window_close"}


class StaffAllowanceGiveLine(models.TransientModel):
    _name = "staff.allowance.give.line"
    _description = "Give an Allowance: Personal Limit"

    wizard_id = fields.Many2one("staff.allowance.give", required=True,
                                ondelete="cascade")
    pos_category_id = fields.Many2one("pos.category", string="POS Category",
                                      required=True)
    daily_limit = fields.Integer(required=True, default=1)
    policy = fields.Selection(_policy_selection, string="At the Limit",
                              default="block", required=True)
    tolerance = fields.Integer(default=0)
