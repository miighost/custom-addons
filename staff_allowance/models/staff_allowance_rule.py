from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

REASON_LIMIT_REACHED = "limit_reached"
REASON_TOLERANCE_EXCEEDED = "tolerance_exceeded"
REASON_BAD_QTY = "bad_qty"


class StaffAllowanceRule(models.Model):
    """A cap on one POS category for one person.

    No rule means no cap. Nothing in this module restricts anybody until a
    rule exists for that exact person and that exact POS category, so
    installing it changes nothing and capping one employee's coffee leaves
    everyone else untouched.

    All the decision logic lives here as model-level methods, so the REST
    API, the backend and the constraint cannot drift apart.
    """

    _name = "staff.allowance.rule"
    _description = "Allowance Rule"
    _inherit = ["staff.allowance.beneficiary.mixin"]
    _order = "beneficiary_name, pos_category_id"

    pos_category_id = fields.Many2one(
        "pos.category", string="POS Category", required=True, index=True,
        ondelete="cascade",
    )
    daily_limit = fields.Integer(
        required=True, default=10,
        help="Units allowed per day. 0 blocks this category for this person.",
    )
    count_mode = fields.Selection(
        [("qty", "Units ordered"), ("order", "Number of orders")],
        default="qty", required=True,
        help="Units: a limit of 10 means 10 items.\n"
             "Orders: a limit of 10 means 10 separate orders.",
    )
    policy = fields.Selection(
        [("block", "Block the order"),
         ("approval", "Allow, but require approval"),
         ("allow", "Allow and flag as over limit")],
        string="At the Limit", default="block", required=True,
    )
    tolerance = fields.Integer(
        default=0,
        help="Extra units tolerated beyond the limit when the policy is not "
             "Block. 0 means no extra cap.",
    )
    active = fields.Boolean(default=True,
                            help="Archive a rule to give this person free "
                                 "access again, without losing the setting.")

    used_today = fields.Integer(compute="_compute_today", string="Used Today")
    remaining_today = fields.Integer(compute="_compute_today", string="Remaining")
    over_today = fields.Integer(compute="_compute_today", string="Over By")
    status = fields.Selection(
        [("ok", "Available"),
         ("near", "Almost Used Up"),
         ("reached", "Limit Reached"),
         ("over", "Over Limit")],
        compute="_compute_today", string="Today",
    )
    resets_at = fields.Datetime(compute="_compute_today")

    # ------------------------------------------------------------------
    # Constraints
    # ------------------------------------------------------------------
    @api.constrains("partner_id", "pos_category_id")
    def _check_unique_rule(self):
        for rule in self:
            duplicate = self.with_context(active_test=False).search(
                self._beneficiary_domain(rule._beneficiary()) + [
                    ("pos_category_id", "=", rule.pos_category_id.id),
                    ("id", "!=", rule.id),
                ], limit=1)
            if duplicate:
                raise ValidationError(
                    _("%(who)s already has a rule for %(category)s.",
                      who=rule.beneficiary_name,
                      category=rule.pos_category_id.display_name)
                )

    @api.constrains("daily_limit", "tolerance")
    def _check_limits(self):
        for rule in self:
            if rule.daily_limit < 0 or rule.tolerance < 0:
                raise ValidationError(_("Limits cannot be negative."))

    def _compute_display_name(self):
        for rule in self:
            rule.display_name = "%s / %s" % (
                rule.beneficiary_name or "",
                rule.pos_category_id.display_name or "")

    # ------------------------------------------------------------------
    # Live figures for the Allowance tab
    # ------------------------------------------------------------------
    @api.depends("partner_id", "pos_category_id", "daily_limit", "count_mode",
                 "active")
    def _compute_today(self):
        for rule in self:
            beneficiary = rule._beneficiary()
            if not beneficiary or not rule.pos_category_id:
                rule.used_today = rule.remaining_today = rule.over_today = 0
                rule.status = False
                rule.resets_at = False
                continue
            used = self._used_on(beneficiary, rule.pos_category_id,
                                 rule._local_today(beneficiary),
                                 rule.count_mode)
            limit = rule.daily_limit
            rule.used_today = used
            rule.remaining_today = max(limit - used, 0)
            rule.over_today = max(used - limit, 0)
            rule.resets_at = rule._resets_at(beneficiary)
            if used > limit:
                rule.status = "over"
            elif used >= limit:
                rule.status = "reached"
            elif limit and used >= limit * 0.8:
                rule.status = "near"
            else:
                rule.status = "ok"

    # ------------------------------------------------------------------
    # Keep the stored usage rows aligned when a rule changes
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        rules = super().create(vals_list)
        rules._refresh_usage()
        return rules

    def write(self, vals):
        result = super().write(vals)
        self._refresh_usage()
        return result

    def unlink(self):
        keys = self._usage_keys()
        result = super().unlink()
        self.env["staff.allowance.usage"]._refresh_keys(keys)
        return result

    def _usage_keys(self):
        keys = set()
        for rule in self:
            beneficiary = rule._beneficiary()
            if beneficiary and rule.pos_category_id:
                keys.add((beneficiary.id, rule.pos_category_id.id,
                          rule._local_today(beneficiary)))
        return keys

    def _refresh_usage(self):
        self.env["staff.allowance.usage"]._refresh_keys(self._usage_keys())

    # ==================================================================
    # THE ENGINE
    # ==================================================================
    @api.model
    def _categories_of_product(self, product):
        """All the POS categories a product sits in."""
        if not product:
            return self.env["pos.category"]
        template = product.product_tmpl_id
        if "pos_categ_ids" in template._fields:
            return template.pos_categ_ids
        if "pos_categ_id" in template._fields:  # older field name
            return template.pos_categ_id
        return self.env["pos.category"]

    @api.model
    def _category_of_product(self, product):
        """The product's first POS category."""
        return self._categories_of_product(product)[:1]

    @api.model
    def _counted_categories(self, beneficiary, product):
        """The POS categories a sale of `product` counts against for `beneficiary`.

        A product can sit in several POS categories, and a category can have
        parents ("Drinks / Coffee"). The sale counts against every one of them
        that caps this person, so a limit on Drinks also covers Coffee. When
        none does, it counts against nothing: people without a rule or plan
        for it leave no allowance records at all.
        """
        beneficiary = self._allowance_contact(beneficiary)
        categories = self.env["pos.category"]
        for category in self._categories_of_product(product):
            while category and category not in categories:
                categories |= category
                category = category.parent_id
        return categories.filtered(
            lambda category: self._resolve(beneficiary, category)[0] != "free")

    @api.model
    def _resolve(self, beneficiary, pos_category):
        """Find the rule that applies. Returns (origin, values-dict or None).

        origin is 'personal', 'plan' or 'free'. 'free' means no cap at all.
        """
        if not beneficiary or not pos_category:
            return ("free", None)

        rule = self.sudo().search(
            self._beneficiary_domain(beneficiary) + [
                ("pos_category_id", "=", pos_category.id)
            ], limit=1)
        if rule:
            return ("personal", {
                "limit": rule.daily_limit,
                "count_mode": rule.count_mode,
                "policy": rule.policy,
                "tolerance": rule.tolerance,
            })

        plan = beneficiary.allowance_plan_id
        if plan.active:  # an archived plan frees everyone on it
            line = plan.line_ids.filtered(
                lambda l: l.pos_category_id == pos_category)
            if line:
                entry = line[0]
                return ("plan", {
                    "limit": entry.daily_limit,
                    "count_mode": entry.count_mode,
                    "policy": entry.policy,
                    "tolerance": entry.tolerance,
                })

        return ("free", None)

    @api.model
    def _used_on(self, beneficiary, pos_category, day, count_mode="qty",
                 exclude_ids=None, before=None):
        Order = self.env["staff.allowance.order"].sudo()
        domain = Order._beneficiary_domain(beneficiary) + [
            ("pos_category_id", "=", pos_category.id),
            ("order_date", "=", day),
            ("state", "in", ("draft", "done")),
        ]
        if exclude_ids:
            domain.append(("id", "not in", list(exclude_ids)))
        if before and isinstance(before.id, int):
            # Only orders placed before `before`.
            domain += ["|", ("order_datetime", "<", before.order_datetime),
                       "&", ("order_datetime", "=", before.order_datetime),
                       ("id", "<", before.id)]
        orders = Order.search(domain)
        return len(orders) if count_mode == "order" else sum(orders.mapped("qty"))

    @api.model
    def _evaluate(self, beneficiary, pos_category, increment=0, day=None,
                  exclude_ids=None, before=None):
        """Describe the quota, and whether `increment` more would fit.

        When no rule applies, `restricted` is False and `limit`/`remaining`
        are null — the app must not treat that as "nothing left".
        """
        beneficiary = self._allowance_contact(beneficiary)
        day = day or self._local_today(beneficiary)
        origin, config = self._resolve(beneficiary, pos_category)

        result = {
            "category_id": pos_category.id if pos_category else None,
            "category_name": pos_category.display_name if pos_category else None,
            "day": fields.Date.to_string(day),
            "origin": origin,
            "restricted": origin != "free",
            "limit": None,
            "used": 0,
            "remaining": None,
            "count_mode": None,
            "policy": None,
            "over_limit": False,
            "overdraft": 0,
            "resets_at": fields.Datetime.to_string(
                self._resets_at(beneficiary)) if beneficiary else None,
            "ok": True,
            "requires_approval": False,
            "reason": False,
            "message": False,
        }

        if increment < 0:
            result.update(ok=False, reason=REASON_BAD_QTY,
                          message=_("The quantity must be greater than zero."))
            return result

        if origin == "free":
            # No rule for this person and this category: nothing to enforce.
            if pos_category and beneficiary:
                result["used"] = self._used_on(beneficiary, pos_category, day,
                                               "qty", exclude_ids, before)
            return result

        limit = config["limit"]
        count_mode = config["count_mode"]
        used = self._used_on(beneficiary, pos_category, day, count_mode,
                             exclude_ids, before)
        step = increment if count_mode == "qty" else (1 if increment else 0)
        overdraft = max(used + step - limit, 0)

        result.update({
            "limit": limit,
            "used": used,
            "remaining": max(limit - used, 0),
            "count_mode": count_mode,
            "policy": config["policy"],
            "over_limit": bool(overdraft),
            "overdraft": overdraft,
        })

        if overdraft:
            unit = _("orders") if count_mode == "order" else _("items")
            if config["policy"] == "block":
                result.update(
                    ok=False, reason=REASON_LIMIT_REACHED,
                    message=_("Daily %(category)s limit reached: %(used)s of "
                              "%(limit)s %(unit)s used today. It resets tomorrow.",
                              category=pos_category.display_name, used=used,
                              limit=limit, unit=unit))
            elif config["tolerance"] and overdraft > config["tolerance"]:
                result.update(
                    ok=False, reason=REASON_TOLERANCE_EXCEEDED,
                    message=_("Daily %(category)s limit of %(limit)s %(unit)s "
                              "reached, and the %(extra)s extra allowed have "
                              "been used too.",
                              category=pos_category.display_name, limit=limit,
                              unit=unit, extra=config["tolerance"]))
            else:
                result["requires_approval"] = config["policy"] == "approval"

        return result

    @api.model
    def _place_order(self, beneficiary, pos_category=None, product=None, qty=1,
                     source="backend", note=None):
        """Record an order, or log a blocked attempt. Never raises."""
        beneficiary = self._allowance_contact(beneficiary)
        Order = self.env["staff.allowance.order"].sudo()
        Attempt = self.env["staff.allowance.attempt"].sudo()
        pos_category = pos_category or self._counted_categories(beneficiary, product)[:1]

        qty = int(qty or 0)
        result = self._evaluate(beneficiary, pos_category, increment=qty)
        if qty <= 0:
            result.update(ok=False, reason=REASON_BAD_QTY,
                          message=_("The quantity must be greater than zero."))

        result["order"] = Order.browse()
        result["attempt"] = Attempt.browse()

        if not result["ok"]:
            result["attempt"] = Attempt.create({
                **Attempt._beneficiary_vals(beneficiary),
                "pos_category_id": pos_category.id if pos_category else False,
                "product_id": product.id if product else False,
                "qty": qty,
                "reason": result["reason"],
                "message": result["message"],
                "source": source,
                "limit_at_attempt": result["limit"] or 0,
                "used_at_attempt": result["used"],
            })
            return result

        if not result["restricted"]:
            # No rule or plan covers this: allowed, and nothing to track.
            return result

        try:
            with self.env.cr.savepoint():
                result["order"] = Order.create({
                    **Order._beneficiary_vals(beneficiary),
                    "pos_category_id": pos_category.id if pos_category else False,
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
                "pos_category_id": pos_category.id if pos_category else False,
                "product_id": product.id if product else False,
                "qty": qty,
                "reason": REASON_LIMIT_REACHED,
                "message": message,
                "source": source,
                "limit_at_attempt": result["limit"] or 0,
                "used_at_attempt": result["used"],
            })
            return result

        refreshed = self._evaluate(beneficiary, pos_category)
        result.update({k: refreshed[k] for k in
                       ("used", "remaining", "over_limit", "overdraft")})
        return result

    # ------------------------------------------------------------------
    def action_view_today_orders(self):
        self.ensure_one()
        beneficiary = self._beneficiary()
        return {
            "type": "ir.actions.act_window",
            "name": _("Today's Orders"),
            "res_model": "staff.allowance.order",
            "view_mode": "list,form",
            "domain": self._beneficiary_domain(beneficiary) + [
                ("pos_category_id", "=", self.pos_category_id.id),
                ("order_date", "=", self._local_today(beneficiary)),
            ],
        }

    @api.model
    def _log_pos_block(self, partner, category, qty, evaluation, message, source="pos"):
        """Record a refused basket in Blocked Attempts.

        The cashier (or app user) may try again on the same basket; within a
        few minutes that is the same attempt, not a new one.
        """
        Attempt = self.env["staff.allowance.attempt"].sudo()
        recent = fields.Datetime.subtract(fields.Datetime.now(), minutes=5)
        if Attempt.search_count([
                ("partner_id", "=", partner.id),
                ("pos_category_id", "=", category.id),
                ("qty", "=", qty), ("source", "=", source),
                ("attempt_datetime", ">=", recent)], limit=1):
            return
        Attempt.create({
            **Attempt._beneficiary_vals(partner),
            "pos_category_id": category.id,
            "qty": qty,
            "reason": evaluation["reason"],
            "message": message,
            "source": source,
            "limit_at_attempt": evaluation["limit"] or 0,
            "used_at_attempt": evaluation["used"],
        })

    # ------------------------------------------------------------------
    # Called from the POS screen to warn the cashier
    # ------------------------------------------------------------------
    @api.model
    def check_pos_basket(self, partner_id, lines, source="pos"):
        """What the POS should tell the cashier about a basket.

        Records nothing, except a Blocked Attempt when the basket is refused.

        lines: [{"product_id": int, "qty": number}]
        Returns {"blocked": bool, "messages": [str], "warnings": [str],
        "details": [...]}. `blocked` means a rule set to Block, or a used-up
        tolerance, refuses the basket: `messages` say why and the sale must
        not go through. Otherwise `warnings` list what goes over and the
        cashier may sell anyway. Everything is empty when nothing is capped.
        """
        result = {"blocked": False, "messages": [], "warnings": [], "details": []}
        partner = self.env["res.partner"].sudo().browse(int(partner_id or 0)).exists()
        if not partner or not lines:
            return result

        Product = self.env["product.product"].sudo()
        wanted = {}
        for line in lines:
            product = Product.browse(int(line.get("product_id") or 0)).exists()
            qty = int(round(float(line.get("qty") or 0)))
            if not product or qty <= 0:
                continue
            for category in self._counted_categories(partner, product):
                wanted[category] = wanted.get(category, 0) + qty

        for category, qty in wanted.items():
            evaluation = self._evaluate(partner, category, increment=qty)
            if not evaluation["restricted"] or (
                    evaluation["ok"] and not evaluation["over_limit"]):
                continue
            blocked = not evaluation["ok"]
            result["details"].append({
                "category_id": category.id,
                "category_name": category.display_name,
                "limit": evaluation["limit"],
                "used": evaluation["used"],
                "in_basket": qty,
                "over_limit": evaluation["over_limit"],
                "overdraft": evaluation["overdraft"],
                "blocked": blocked,
            })
            values = dict(who=partner.display_name, category=category.display_name,
                          used=evaluation["used"], limit=evaluation["limit"],
                          basket=qty)
            if blocked:
                message = _(
                    "%(who)s cannot take %(basket)s more %(category)s today: "
                    "the daily limit is %(limit)s and %(used)s already used.",
                    **values)
                result["blocked"] = True
                result["messages"].append(message)
                self._log_pos_block(partner, category, qty, evaluation, message, source)
            else:
                result["warnings"].append(_(
                    "%(who)s is over the daily %(category)s allowance: "
                    "%(used)s already used of %(limit)s, %(basket)s more in "
                    "this order.", **values))
        return result
