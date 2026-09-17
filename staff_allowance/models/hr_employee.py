from odoo import fields, models


class HrEmployee(models.Model):
    """Allowances belong to the employee's work contact.

    That is the contact the POS sells to and the one Odoo links to their
    user, so limits are edited on the contact and only shown here: one set of
    limits and one counter per person.
    """

    _inherit = "hr.employee"

    allowance_plan_id = fields.Many2one(related="work_contact_id.allowance_plan_id")
    allowance_rule_ids = fields.One2many(related="work_contact_id.allowance_rule_ids")
    allowance_order_count = fields.Integer(
        related="work_contact_id.allowance_order_count")
    allowance_over_count = fields.Integer(
        related="work_contact_id.allowance_over_count")

    def action_edit_allowance(self):
        self.ensure_one()
        return self.work_contact_id.action_give_allowance()

    def action_view_allowance_orders(self):
        self.ensure_one()
        return self.work_contact_id.action_view_allowance_orders()
