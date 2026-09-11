from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

# Reasons an order can be refused. Kept as constants so the model, the
# constraint and the REST controller all speak the same language.
REASON_NOT_ALLOWED = "not_allowed"
REASON_LIMIT_REACHED = "limit_reached"
REASON_OVERDRAFT_EXCEEDED = "overdraft_exceeded"
REASON_PRODUCT_NOT_ALLOWED = "product_not_allowed"
REASON_BAD_QTY = "bad_qty"


class StaffAllowanceCategory(models.Model):
    _name = "staff.allowance.category"
    _description = "Allowance Category"
    _order = "sequence, name"

    name = fields.Char(required=True, translate=True)
    code = fields.Char(
        required=True,
        copy=False,
        help="Stable technical identifier used by the mobile app, e.g. 'coffee'. "
             "Do not change it once the app is live.",
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    color = fields.Integer()
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company, required=True
    )

    # --- quota ---------------------------------------------------------
    daily_limit = fields.Integer(
        default=10,
        required=True,
        help="Used when 'If Nothing Is Assigned' is set to apply it, and as the "
             "suggested value when you assign someone. Overridden by a plan, "
             "and then by a personal allowance line.",
    )
    count_mode = fields.Selection(
        [("qty", "Units ordered"), ("order", "Number of orders")],
        default="qty",
        required=True,
        help="Units: a limit of 10 means 10 coffees.\n"
             "Orders: a limit of 10 means 10 separate orders, whatever the quantity.",
    )
    applies_to = fields.Selection(
        [("all", "Employees and Contacts"),
         ("employee", "Employees only"),
         ("partner", "Contacts only")],
        default="employee",
        required=True,
    )
    fallback = fields.Selection(
        [("unlimited", "Free - no limit unless assigned"),
         ("default_limit", "Apply the default limit below"),
         ("blocked", "Not allowed unless assigned")],
        string="If Nothing Is Assigned",
        default="unlimited",
        required=True,
        help="What happens to someone who has no personal allowance line and "
             "no plan entry for this category.\n"
             "Free: they order without any cap. This is the default -- an "
             "allowance only ever restricts once you actually set one.\n"
             "Apply the default limit: the Daily Limit below caps everyone.\n"
             "Not allowed: they cannot order at all until you assign them.",
    )

    # --- what happens at the limit --------------------------------------
    overdraft_policy = fields.Selection(
        [("block", "Block the order"),
         ("approval", "Allow, but require approval"),
         ("allow", "Allow and flag as over limit")],
        string="When the Limit Is Reached",
        default="block",
        required=True,
        help="Block: the app receives an error and nothing is recorded except a "
             "blocked attempt.\n"
             "Approval: the order is created as To Approve and flagged over limit.\n"
             "Allow: the order goes through, flagged over limit for reporting.",
    )
    overdraft_limit = fields.Integer(
        string="Max Over Limit",
        default=0,
        help="Extra units tolerated beyond the daily limit when the policy is not "
             "Block. 0 means no extra cap.",
    )

    product_ids = fields.Many2many(
        "product.product",
        string="Allowed Products",
        help="Leave empty to allow any product in this category.",
    )

    line_ids = fields.One2many("staff.allowance.line", "category_id")
    order_ids = fields.One2many("staff.allowance.order", "category_id")

    line_count = fields.Integer(compute="_compute_counts")
    today_order_count = fields.Integer(compute="_compute_counts")
    today_over_count = fields.Integer(compute="_compute_counts")

    # ------------------------------------------------------------------
    # Constraints
    # ------------------------------------------------------------------
    @api.constrains("code")
    def _check_code_unique(self):
        for record in self:
            if not record.code:
                continue
            duplicate = self.with_context(active_test=False).search(
                [("code", "=", record.code), ("id", "!=", record.id)], limit=1
            )
            if duplicate:
                raise ValidationError(
                    _("The code %(code)s is already used by the category %(name)s.",
                      code=record.code, name=duplicate.name)
                )

    @api.constrains("daily_limit", "overdraft_limit")
    def _check_limits(self):
        for record in self:
            if record.daily_limit < 0 or record.overdraft_limit < 0:
                raise ValidationError(_("Limits cannot be negative."))

    # ------------------------------------------------------------------
    def _compute_counts(self):
        Order = self.env["staff.allowance.order"].sudo()
        for category in self:
            today = self.env["staff.allowance.order"]._local_today(self.env.user)
            category.line_count = len(category.line_ids)
            category.today_order_count = Order.search_count([
                ("category_id", "=", category.id),
                ("order_date", "=", today),
                ("state", "=", "done"),
            ])
            category.today_over_count = Order.search_count([
                ("category_id", "=", category.id),
                ("order_date", "=", today),
                ("is_over_limit", "=", True),
                ("state", "in", ("draft", "done")),
            ])

    # ------------------------------------------------------------------
    # Quota resolution -- the cascade
    # ------------------------------------------------------------------
    def _limit_for(self, beneficiary):
        """Resolve the daily limit for a beneficiary.

        Cascade, most specific first:
          1. personal allowance line   (Allowance tab on the employee/contact)
          2. plan line                 (the tier assigned to them)
          3. the category fallback     (free by default)

        Returns (allowed: bool, unlimited: bool, limit: int, origin: str).
        When `unlimited` is True the limit is meaningless -- nothing is capped.
        """
        self.ensure_one()
        if not beneficiary:
            return (False, False, 0, "none")

        is_employee = beneficiary._name == "hr.employee"
        if self.applies_to == "employee" and not is_employee:
            return (False, False, 0, "scope")
        if self.applies_to == "partner" and is_employee:
            return (False, False, 0, "scope")

        Line = self.env["staff.allowance.line"].sudo()
        line = Line.search(
            Line._beneficiary_domain(beneficiary) + [("category_id", "=", self.id)],
            limit=1,
        )
        if line:
            if not line.allowed:
                return (False, False, 0, "personal")
            return (True, line.unlimited,
                    0 if line.unlimited else line.daily_limit, "personal")

        plan = beneficiary.allowance_plan_id
        if plan:
            plan_line = plan.line_ids.filtered(lambda l: l.category_id == self)
            if plan_line:
                entry = plan_line[0]
                return (True, entry.unlimited,
                        0 if entry.unlimited else entry.daily_limit, "plan")
            if plan.strict:
                # The plan is the complete list; anything outside it is blocked.
                return (False, False, 0, "plan")

        # Nothing assigned anywhere. Default is free -- an allowance only ever
        # restricts once somebody actually sets one.
        if self.fallback == "blocked":
            return (False, False, 0, "category")
        if self.fallback == "default_limit":
            return (True, False, self.daily_limit, "category")
        return (True, True, 0, "category")

    def _used_today(self, beneficiary, day=None, exclude_ids=None):
        """Units (or orders) already consumed by the beneficiary on `day`."""
        self.ensure_one()
        Order = self.env["staff.allowance.order"].sudo()
        if not beneficiary:
            return 0
        day = day or Order._local_today(beneficiary)
        domain = Order._beneficiary_domain(beneficiary) + [
            ("category_id", "=", self.id),
            ("order_date", "=", day),
            ("state", "in", ("draft", "done")),
        ]
        if exclude_ids:
            domain.append(("id", "not in", list(exclude_ids)))
        orders = Order.search(domain)
        if self.count_mode == "order":
            return len(orders)
        return sum(orders.mapped("qty"))

    # ------------------------------------------------------------------
    # The single source of truth used by the API, the UI and the constraint
    # ------------------------------------------------------------------
    def _evaluate(self, beneficiary, increment=0, product=None, day=None,
                  exclude_ids=None):
        """Describe the quota, and whether `increment` more units would fit.

        Returns a dict:
            allowed, limit, used, remaining, origin, over_limit, overdraft,
            ok, reason, message, resets_at, day
        `ok` is True when an order of `increment` may be recorded.
        """
        self.ensure_one()
        Order = self.env["staff.allowance.order"].sudo()
        day = day or Order._local_today(beneficiary)
        allowed, unlimited, limit, origin = self._limit_for(beneficiary)
        used = self._used_today(beneficiary, day, exclude_ids=exclude_ids) \
            if allowed else 0
        projected = used + increment
        overdraft = 0 if unlimited else max(projected - limit, 0)

        result = {
            "category_id": self.id,
            "code": self.code,
            "name": self.name,
            "day": fields.Date.to_string(day),
            "allowed": allowed,
            "unlimited": unlimited,
            # null rather than 0 when uncapped, so an app testing
            # `remaining == 0` never blocks an unlimited user by accident
            "limit": None if unlimited else limit,
            "used": used,
            "remaining": None if unlimited else max(limit - used, 0),
            "origin": origin,
            "count_mode": self.count_mode,
            "overdraft_policy": self.overdraft_policy,
            "over_limit": bool(overdraft),
            "overdraft": overdraft,
            "resets_at": fields.Datetime.to_string(Order._resets_at(beneficiary)),
            "ok": True,
            "requires_approval": False,
            "reason": False,
            "message": False,
        }

        if not allowed:
            result.update(
                ok=False,
                reason=REASON_NOT_ALLOWED,
                message=_("%(who)s is not allowed to order from %(category)s.",
                          who=beneficiary.display_name, category=self.name),
            )
            return result

        if increment < 0:
            result.update(ok=False, reason=REASON_BAD_QTY,
                          message=_("The quantity must be greater than zero."))
            return result

        if product and self.product_ids and product not in self.product_ids:
            result.update(
                ok=False,
                reason=REASON_PRODUCT_NOT_ALLOWED,
                message=_("%(product)s is not part of the %(category)s allowance.",
                          product=product.display_name, category=self.name),
            )
            return result

        if unlimited:
            return result

        if overdraft:
            unit = _("orders") if self.count_mode == "order" else _("units")
            if self.overdraft_policy == "block":
                result.update(
                    ok=False,
                    reason=REASON_LIMIT_REACHED,
                    message=_(
                        "Daily %(category)s limit reached: %(used)s of %(limit)s "
                        "%(unit)s used today. It resets tomorrow.",
                        category=self.name, used=used, limit=limit, unit=unit),
                )
                return result
            if self.overdraft_limit and overdraft > self.overdraft_limit:
                result.update(
                    ok=False,
                    reason=REASON_OVERDRAFT_EXCEEDED,
                    message=_(
                        "Daily %(category)s limit of %(limit)s %(unit)s reached, and "
                        "the %(extra)s extra allowed have been used too.",
                        category=self.name, limit=limit, unit=unit,
                        extra=self.overdraft_limit),
                )
                return result
            result["requires_approval"] = self.overdraft_policy == "approval"

        return result

    # ------------------------------------------------------------------
    def _place_order(self, beneficiary, qty=1, product=None, source="backend",
                     note=None):
        """Record an order, or log a blocked attempt. Never raises.

        Returns the `_evaluate` dict, plus 'order' (recordset or empty) and
        'attempt' (recordset or empty).
        """
        self.ensure_one()
        Order = self.env["staff.allowance.order"].sudo()
        Attempt = self.env["staff.allowance.attempt"].sudo()

        qty = int(qty or 0)
        increment = qty if self.count_mode == "qty" else 1
        if qty <= 0:
            result = self._evaluate(beneficiary, 0, product)
            result.update(ok=False, reason=REASON_BAD_QTY,
                          message=_("The quantity must be greater than zero."))
            increment = 0
        else:
            result = self._evaluate(beneficiary, increment, product)

        result["order"] = Order.browse()
        result["attempt"] = Attempt.browse()

        if not result["ok"]:
            result["attempt"] = Attempt.create({
                **Attempt._beneficiary_vals(beneficiary),
                "category_id": self.id,
                "qty": qty,
                "product_id": product.id if product else False,
                "reason": result["reason"],
                "message": result["message"],
                "source": source,
                "limit_at_attempt": result["limit"],
                "used_at_attempt": result["used"],
            })
            return result

        try:
            # Savepoint: if the row lock let a concurrent request in first, the
            # constraint fires here. Roll back just this insert, then log the
            # attempt like any other refusal instead of failing the request.
            with self.env.cr.savepoint():
                result["order"] = Order.create({
                    **Order._beneficiary_vals(beneficiary),
                    "category_id": self.id,
                    "product_id": product.id if product else False,
                    "qty": qty,
                    "source": source,
                    "note": note or False,
                    "state": "draft" if result["requires_approval"] else "done",
                })
        except ValidationError as exc:
            message = exc.args[0] if exc.args else str(exc)
            result.update(ok=False, reason=REASON_LIMIT_REACHED, message=message)
            result["order"] = Order.browse()
            result["attempt"] = Attempt.create({
                **Attempt._beneficiary_vals(beneficiary),
                "category_id": self.id,
                "qty": qty,
                "product_id": product.id if product else False,
                "reason": REASON_LIMIT_REACHED,
                "message": message,
                "source": source,
                "limit_at_attempt": result["limit"],
                "used_at_attempt": result["used"],
            })
            return result
        # Refresh the figures now that the order exists.
        refreshed = self._evaluate(beneficiary, 0, None)
        result.update({k: refreshed[k] for k in
                       ("used", "remaining", "over_limit", "overdraft")})
        return result

    # ------------------------------------------------------------------
    def action_open_lines(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Allowances - %s", self.name),
            "res_model": "staff.allowance.line",
            "view_mode": "list,form",
            "domain": [("category_id", "=", self.id)],
            "context": {"default_category_id": self.id},
        }

    def action_open_orders(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Orders - %s", self.name),
            "res_model": "staff.allowance.order",
            "view_mode": "list,pivot,form",
            "domain": [("category_id", "=", self.id)],
            "context": {"default_category_id": self.id,
                        "search_default_today": 1},
        }
