import pytz

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import SQL


class StaffAllowanceOrder(models.Model):
    """One consumption event. Quotas are derived from these rows."""

    _name = "staff.allowance.order"
    _description = "Allowance Order"
    _inherit = ["staff.allowance.beneficiary.mixin", "mail.thread"]
    _order = "order_datetime desc, id desc"

    name = fields.Char(required=True, copy=False, readonly=True,
                       default=lambda s: _("New"))
    # History must survive the deletion of a contact: restrict, not cascade.
    employee_id = fields.Many2one("hr.employee", string="Employee", index=True,
                                  ondelete="restrict", tracking=True)
    partner_id = fields.Many2one("res.partner", string="Contact", index=True,
                                 ondelete="restrict", tracking=True)
    pos_category_id = fields.Many2one("pos.category", string="POS Category",
                                      required=True, index=True,
                                      ondelete="restrict", tracking=True)
    product_id = fields.Many2one("product.product", ondelete="restrict")
    qty = fields.Integer(default=1, required=True, string="Quantity",
                         tracking=True)
    note = fields.Char()

    order_datetime = fields.Datetime(default=fields.Datetime.now, required=True,
                                     index=True)
    # The beneficiary's LOCAL day, stamped once, so a 23:58 order stays on
    # its own day even if it is processed a minute later.
    order_date = fields.Date(compute="_compute_order_date", store=True,
                             index=True, readonly=False)

    state = fields.Selection(
        [("draft", "To Approve"), ("done", "Done"),
         ("refused", "Refused"), ("cancel", "Cancelled")],
        default="done", required=True, tracking=True,
        help="To Approve and Done consume the allowance. "
             "Refused and Cancelled do not.")
    source = fields.Selection(
        [("app", "Mobile App"), ("backend", "Backend"), ("pos", "Point of Sale")],
        default="backend", required=True)

    is_over_limit = fields.Boolean(string="Over Limit",
                                   compute="_compute_over_limit", store=True,
                                   readonly=True, index=True, copy=False)
    over_by = fields.Integer(string="Over By", compute="_compute_over_limit",
                             store=True, readonly=True)
    pos_order_id = fields.Many2one("pos.order", string="POS Order",
                                   ondelete="set null", index=True, copy=False,
                                   readonly=True)
    approver_id = fields.Many2one("res.users", string="Approved By",
                                  readonly=True, copy=False)
    approval_date = fields.Datetime(readonly=True, copy=False)

    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals["name"] == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "staff.allowance.order") or _("New")
        orders = super().create(vals_list)
        orders._lock_beneficiaries()
        orders._sync_usage()
        return orders

    def write(self, vals):
        before = self._usage_keys()
        result = super().write(vals)
        self.env["staff.allowance.usage"]._refresh_keys(
            before | self._usage_keys())
        return result

    def unlink(self):
        keys = self._usage_keys()
        result = super().unlink()
        self.env["staff.allowance.usage"]._refresh_keys(keys)
        return result

    def _lock_beneficiaries(self):
        """Make two simultaneous orders for the same person conflict.

        Odoo runs each request in REPEATABLE READ, so the limit check reads a
        snapshot taken when the request started. `SELECT ... FOR UPDATE` only
        makes the second request wait -- it still cannot see the first order,
        and both pass. Updating the row is what works: the second request
        then fails with a serialization error, Odoo retries it, and the retry
        sees the first order. The constraint having already run does not
        matter, since the whole transaction is thrown away.
        """
        for table, records in (("hr_employee", self.employee_id),
                               ("res_partner", self.partner_id)):
            if records:
                self.env.cr.execute(SQL(
                    "UPDATE %s SET write_date = write_date WHERE id IN %s",
                    SQL.identifier(table), tuple(records.ids)))

    def _usage_keys(self):
        keys = set()
        for order in self:
            beneficiary = order._beneficiary()
            if beneficiary and order.pos_category_id and order.order_date:
                keys.add((beneficiary._name, beneficiary.id,
                          order.pos_category_id.id, order.order_date))
        return keys

    def _sync_usage(self):
        self.env["staff.allowance.usage"]._refresh_keys(self._usage_keys())

    # ------------------------------------------------------------------
    @api.depends("order_datetime", "employee_id", "partner_id")
    def _compute_order_date(self):
        for order in self:
            beneficiary = order._beneficiary()
            if not order.order_datetime or not beneficiary:
                order.order_date = False
                continue
            tz = order._beneficiary_tz(beneficiary)
            order.order_date = (
                pytz.utc.localize(order.order_datetime).astimezone(tz).date())

    @api.depends("employee_id", "partner_id", "pos_category_id", "qty",
                 "order_date", "state")
    def _compute_over_limit(self):
        Rule = self.env["staff.allowance.rule"].sudo()
        for order in self:
            beneficiary = order._beneficiary()
            if not beneficiary or not order.pos_category_id or \
                    order.state not in ("draft", "done"):
                order.is_over_limit = False
                order.over_by = 0
                continue
            evaluation = Rule._evaluate(
                beneficiary, order.pos_category_id, increment=order.qty,
                day=order.order_date, exclude_ids=order.ids)
            order.is_over_limit = evaluation["over_limit"]
            order.over_by = evaluation["overdraft"]

    @api.onchange("product_id")
    def _onchange_product_id(self):
        """Default the category from the product's own POS category."""
        if self.product_id and not self.pos_category_id:
            category = self.env["staff.allowance.rule"]._category_of_product(
                self.product_id)
            if category:
                self.pos_category_id = category

    # ------------------------------------------------------------------
    # Final safety net for anything written directly (backend, imports).
    # ------------------------------------------------------------------
    @api.constrains("employee_id", "partner_id", "pos_category_id", "qty",
                    "order_date", "state")
    def _check_allowance(self):
        Rule = self.env["staff.allowance.rule"].sudo()
        for order in self:
            if order.state not in ("draft", "done"):
                continue
            pos_sale = order.pos_order_id
            if pos_sale.state in ("paid", "done") \
                    and pos_sale.partner_id == order.partner_id:
                # A paid POS sale already happened. Recording it must never
                # fail -- the over-limit flag is what reports it. Decided
                # from the linked sale, not from a context key: constraints
                # run as superuser and any RPC caller sets the context.
                continue
            if order.qty <= 0:
                raise ValidationError(_("The quantity must be greater than zero."))
            evaluation = Rule._evaluate(
                order._beneficiary(), order.pos_category_id,
                increment=order.qty, day=order.order_date,
                exclude_ids=order.ids)
            if not evaluation["ok"]:
                raise ValidationError(evaluation["message"])

    # ------------------------------------------------------------------
    def action_approve(self):
        for order in self:
            if order.state != "draft":
                raise UserError(_("Only orders waiting for approval can be approved."))
        self.write({"state": "done", "approver_id": self.env.user.id,
                    "approval_date": fields.Datetime.now()})

    def action_refuse(self):
        self.write({"state": "refused", "approver_id": self.env.user.id,
                    "approval_date": fields.Datetime.now()})

    def action_cancel(self):
        self.write({"state": "cancel"})

    def action_reset_to_draft(self):
        self.write({"state": "draft", "approver_id": False,
                    "approval_date": False})

    def _compute_display_name(self):
        for order in self:
            order.display_name = "%s - %s" % (order.name or "",
                                              order.beneficiary_name or "")

    def _to_json(self):
        self.ensure_one()
        return {
            "id": self.id,
            "reference": self.name,
            "beneficiary_type": self.beneficiary_type,
            "beneficiary_name": self.beneficiary_name,
            "category_id": self.pos_category_id.id,
            "category_name": self.pos_category_id.display_name,
            "product_id": self.product_id.id or None,
            "product_name": self.product_id.display_name if self.product_id else None,
            "qty": self.qty,
            "state": self.state,
            "is_over_limit": self.is_over_limit,
            "over_by": self.over_by,
            "order_date": fields.Date.to_string(self.order_date),
            "order_datetime": fields.Datetime.to_string(self.order_datetime),
        }
