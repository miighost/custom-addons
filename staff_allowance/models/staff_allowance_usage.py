from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class StaffAllowanceUsage(models.Model):
    """One stored row per beneficiary / category / day.

    Consumption used to be computed live, which meant it could not be
    searched, grouped or reported on without loading every record into
    memory. This model keeps the same numbers on disk, refreshed whenever an
    order or an allowance line changes, so monitoring views are ordinary
    indexed queries.

    Rows are only created once there is something to record, and a row for a
    past day keeps the limit as it stood that day -- raising someone's limit
    today does not rewrite last week's history.
    """

    _name = "staff.allowance.usage"
    _description = "Daily Allowance Usage"
    _inherit = ["staff.allowance.beneficiary.mixin"]
    _rec_name = "beneficiary_name"
    _order = "day desc, beneficiary_name"

    category_id = fields.Many2one(
        "staff.allowance.category", required=True, index=True, ondelete="cascade"
    )
    day = fields.Date(required=True, index=True)

    used = fields.Integer(string="Used", readonly=True)
    order_count = fields.Integer(string="Orders", readonly=True)
    limit_value = fields.Integer(string="Limit", readonly=True)
    remaining = fields.Integer(readonly=True)
    over_by = fields.Integer(string="Over By", readonly=True)
    status = fields.Selection(
        [("blocked", "Blocked"),
         ("ok", "Available"),
         ("near", "Almost Used Up"),
         ("reached", "Limit Reached"),
         ("over", "Over Limit")],
        readonly=True, index=True,
    )
    origin = fields.Selection(
        [("personal", "Personal Line"),
         ("plan", "Plan"),
         ("category", "Category Default"),
         ("scope", "Out of Scope"),
         ("none", "None")],
        string="Limit From", readonly=True,
    )
    company_id = fields.Many2one(
        related="category_id.company_id", store=True, readonly=True
    )

    @api.constrains("employee_id", "partner_id", "category_id", "day")
    def _check_unique_day(self):
        for usage in self:
            duplicate = self.search(
                self._beneficiary_domain(usage._beneficiary()) + [
                    ("category_id", "=", usage.category_id.id),
                    ("day", "=", usage.day),
                    ("id", "!=", usage.id),
                ], limit=1)
            if duplicate:
                raise ValidationError(
                    _("Usage is already recorded for %(who)s / %(category)s on "
                      "%(day)s.", who=usage.beneficiary_name,
                      category=usage.category_id.name, day=usage.day)
                )

    def _compute_display_name(self):
        for usage in self:
            usage.display_name = "%s - %s - %s" % (
                usage.beneficiary_name or "", usage.category_id.name or "",
                usage.day or "")

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------
    @api.model
    def _status_for(self, allowed, used, limit):
        if not allowed:
            return "blocked"
        if limit and used > limit:
            return "over"
        if limit and used >= limit:
            return "reached"
        if limit and used >= limit * 0.8:
            return "near"
        return "ok"

    @api.model
    def _refresh(self, beneficiary, category, day):
        """Recompute the stored row for one beneficiary/category/day."""
        if not beneficiary or not category or not day:
            return self.browse()

        Usage = self.sudo()
        Order = self.env["staff.allowance.order"].sudo()
        record = Usage.search(
            self._beneficiary_domain(beneficiary) + [
                ("category_id", "=", category.id), ("day", "=", day)
            ], limit=1)

        order_domain = Order._beneficiary_domain(beneficiary) + [
            ("category_id", "=", category.id),
            ("order_date", "=", day),
            ("state", "in", ("draft", "done")),
        ]
        orders = Order.search(order_domain)
        if not orders:
            if record:
                record.unlink()
            return self.browse()

        used = (len(orders) if category.count_mode == "order"
                else sum(orders.mapped("qty")))
        allowed, limit, origin = category._limit_for(beneficiary)
        vals = {
            "used": used,
            "order_count": len(orders),
            "limit_value": limit,
            "remaining": max(limit - used, 0),
            "over_by": max(used - limit, 0),
            "status": self._status_for(allowed, used, limit),
            "origin": origin,
        }
        if record:
            record.write(vals)
            return record
        return Usage.create({
            **self._beneficiary_vals(beneficiary),
            "category_id": category.id,
            "day": day,
            **vals,
        })

    @api.model
    def _refresh_keys(self, keys):
        """keys: iterable of (model_name, res_id, category_id, day)."""
        Category = self.env["staff.allowance.category"].sudo()
        for model_name, res_id, category_id, day in keys:
            beneficiary = self.env[model_name].sudo().browse(res_id).exists()
            category = Category.browse(category_id).exists()
            self._refresh(beneficiary, category, day)

    @api.model
    def action_rebuild_today(self):
        """Rebuild every row for today. Safe to run at any time."""
        Order = self.env["staff.allowance.order"].sudo()
        today_orders = Order.search([("state", "in", ("draft", "done"))])
        keys = set()
        for order in today_orders:
            beneficiary = order._beneficiary()
            if beneficiary and order.category_id and order.order_date:
                keys.add((beneficiary._name, beneficiary.id,
                          order.category_id.id, order.order_date))
        self._refresh_keys(keys)
        return True
