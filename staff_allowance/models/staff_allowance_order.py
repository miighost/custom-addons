import pytz

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class StaffAllowanceOrder(models.Model):
    """One consumption event. The daily quota is derived from these rows."""

    _name = "staff.allowance.order"
    _description = "Allowance Order"
    _inherit = ["staff.allowance.beneficiary.mixin", "mail.thread"]
    _order = "order_datetime desc, id desc"

    name = fields.Char(
        required=True, copy=False, readonly=True, default=lambda s: _("New")
    )
    # History must survive the deletion of a contact: restrict, not cascade.
    employee_id = fields.Many2one(
        "hr.employee", string="Employee", index=True, ondelete="restrict",
        tracking=True,
    )
    partner_id = fields.Many2one(
        "res.partner", string="Contact", index=True, ondelete="restrict",
        tracking=True,
    )
    category_id = fields.Many2one(
        "staff.allowance.category", required=True, index=True,
        ondelete="restrict", tracking=True,
    )
    product_id = fields.Many2one("product.product", ondelete="restrict")
    qty = fields.Integer(default=1, required=True, string="Quantity",
                         tracking=True)
    note = fields.Char()

    order_datetime = fields.Datetime(
        default=fields.Datetime.now, required=True, index=True
    )
    # The beneficiary's LOCAL day. Stamped once, so a 23:58 order stays on
    # its own day even if it is processed a minute later.
    order_date = fields.Date(
        compute="_compute_order_date", store=True, index=True, readonly=False
    )

    state = fields.Selection(
        [("draft", "To Approve"),
         ("done", "Done"),
         ("refused", "Refused"),
         ("cancel", "Cancelled")],
        default="done", required=True, tracking=True,
        help="To Approve and Done consume the allowance. "
             "Refused and Cancelled do not.",
    )
    source = fields.Selection(
        [("app", "Mobile App"), ("backend", "Backend"), ("pos", "Point of Sale")],
        default="backend", required=True,
    )

    is_over_limit = fields.Boolean(
        string="Over Limit", compute="_compute_is_over_limit", store=True,
        readonly=True, index=True, copy=False,
        help="Recorded even though the daily limit was already reached.",
    )
    over_by = fields.Integer(
        string="Over By", compute="_compute_is_over_limit", store=True,
        readonly=True, help="Units beyond the daily limit at the time of ordering.",
    )
    approver_id = fields.Many2one("res.users", string="Approved By",
                                  readonly=True, copy=False)
    approval_date = fields.Datetime(readonly=True, copy=False)

    company_id = fields.Many2one(
        related="category_id.company_id", store=True, readonly=True
    )
    user_id = fields.Many2one(
        related="employee_id.user_id", store=True, readonly=True,
        string="Related User",
    )

    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals["name"] == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "staff.allowance.order"
                ) or _("New")
        # Lock the beneficiary rows before the constraint runs, so two
        # simultaneous taps in the app cannot both slip past the limit.
        self._lock_beneficiaries(vals_list)
        orders = super().create(vals_list)
        orders._sync_usage()
        return orders

    def write(self, vals):
        before = self._usage_keys()
        result = super().write(vals)
        self.env["staff.allowance.usage"]._refresh_keys(
            before | self._usage_keys()
        )
        return result

    def unlink(self):
        keys = self._usage_keys()
        result = super().unlink()
        self.env["staff.allowance.usage"]._refresh_keys(keys)
        return result

    def _usage_keys(self):
        """(model, id, category, day) triples this recordset touches."""
        keys = set()
        for order in self:
            beneficiary = order._beneficiary()
            if beneficiary and order.category_id and order.order_date:
                keys.add((beneficiary._name, beneficiary.id,
                          order.category_id.id, order.order_date))
        return keys

    def _sync_usage(self):
        self.env["staff.allowance.usage"]._refresh_keys(self._usage_keys())

    def _lock_beneficiaries(self, vals_list):
        employee_ids = {v["employee_id"] for v in vals_list if v.get("employee_id")}
        partner_ids = {v["partner_id"] for v in vals_list if v.get("partner_id")}
        if employee_ids:
            self.env.cr.execute(
                "SELECT id FROM hr_employee WHERE id IN %s FOR UPDATE",
                (tuple(employee_ids),),
            )
        if partner_ids:
            self.env.cr.execute(
                "SELECT id FROM res_partner WHERE id IN %s FOR UPDATE",
                (tuple(partner_ids),),
            )

    @api.depends("order_datetime", "employee_id", "partner_id")
    def _compute_order_date(self):
        for order in self:
            beneficiary = order._beneficiary()
            if not order.order_datetime or not beneficiary:
                order.order_date = False
                continue
            tz = order._beneficiary_tz(beneficiary)
            order.order_date = (
                pytz.utc.localize(order.order_datetime).astimezone(tz).date()
            )

    @api.depends("employee_id", "partner_id", "category_id", "qty",
                 "order_date", "state")
    def _compute_is_over_limit(self):
        for order in self:
            beneficiary = order._beneficiary()
            if not beneficiary or not order.category_id or \
                    order.state not in ("draft", "done"):
                order.is_over_limit = False
                order.over_by = 0
                continue
            increment = order.qty if order.category_id.count_mode == "qty" else 1
            evaluation = order.category_id._evaluate(
                beneficiary, increment=increment, day=order.order_date,
                exclude_ids=order.ids,
            )
            order.is_over_limit = evaluation["over_limit"]
            order.over_by = evaluation["overdraft"]

    @api.onchange("category_id")
    def _onchange_category_id(self):
        if self.category_id and self.category_id.product_ids:
            if self.product_id not in self.category_id.product_ids:
                self.product_id = False
            return {"domain": {"product_id": [
                ("id", "in", self.category_id.product_ids.ids)]}}
        return {"domain": {"product_id": []}}

    # ------------------------------------------------------------------
    # Final safety net. `_place_order` on the category is the friendly path;
    # this catches anything written directly (backend, imports, other code).
    # ------------------------------------------------------------------
    @api.constrains("employee_id", "partner_id", "category_id", "qty",
                    "order_date", "state", "product_id")
    def _check_allowance(self):
        for order in self:
            if order.state not in ("draft", "done"):
                continue
            if order.qty <= 0:
                raise ValidationError(_("The quantity must be greater than zero."))

            category = order.category_id
            beneficiary = order._beneficiary()
            increment = order.qty if category.count_mode == "qty" else 1
            evaluation = category._evaluate(
                beneficiary, increment=increment, product=order.product_id,
                day=order.order_date, exclude_ids=order.ids,
            )
            if not evaluation["ok"]:
                raise ValidationError(evaluation["message"])

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_approve(self):
        for order in self:
            if order.state != "draft":
                raise UserError(_("Only orders waiting for approval can be approved."))
        self.write({
            "state": "done",
            "approver_id": self.env.user.id,
            "approval_date": fields.Datetime.now(),
        })

    def action_refuse(self):
        self.write({"state": "refused",
                    "approver_id": self.env.user.id,
                    "approval_date": fields.Datetime.now()})

    def action_cancel(self):
        self.write({"state": "cancel"})

    def action_reset_to_draft(self):
        self.write({"state": "draft", "approver_id": False,
                    "approval_date": False})

    def _compute_display_name(self):
        for order in self:
            order.display_name = "%s - %s" % (
                order.name or "", order.beneficiary_name or ""
            )

    def _to_json(self):
        self.ensure_one()
        return {
            "id": self.id,
            "reference": self.name,
            "beneficiary_type": self.beneficiary_type,
            "beneficiary_id": self._beneficiary().id,
            "beneficiary_name": self.beneficiary_name,
            "category_code": self.category_id.code,
            "category_name": self.category_id.name,
            "product_id": self.product_id.id or None,
            "product_name": self.product_id.display_name if self.product_id else None,
            "qty": self.qty,
            "state": self.state,
            "is_over_limit": self.is_over_limit,
            "over_by": self.over_by,
            "order_date": fields.Date.to_string(self.order_date),
            "order_datetime": fields.Datetime.to_string(self.order_datetime),
        }
