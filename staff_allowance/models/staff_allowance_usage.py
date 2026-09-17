from odoo import _, api, fields, models


class StaffAllowanceUsage(models.Model):
    """One stored row per beneficiary / POS category / day.

    Consumption computed on the fly cannot be searched, grouped or reported
    on. This keeps the same numbers on disk so monitoring views are ordinary
    indexed queries. Rows are created from orders, including for people with
    no rule — you still get to see what was consumed, just with no limit
    against it.

    A row for a past day keeps the limit as it stood that day; raising
    somebody's limit today does not rewrite last week.
    """

    _name = "staff.allowance.usage"
    _description = "Daily Allowance Usage"
    _inherit = ["staff.allowance.beneficiary.mixin"]
    _order = "day desc, beneficiary_name"

    pos_category_id = fields.Many2one("pos.category", string="POS Category",
                                      required=True, index=True,
                                      ondelete="cascade")
    day = fields.Date(required=True, index=True)

    used = fields.Integer(readonly=True)
    order_count = fields.Integer(string="Orders", readonly=True)
    limit_value = fields.Integer(string="Limit", readonly=True)
    remaining = fields.Integer(readonly=True)
    over_by = fields.Integer(string="Over By", readonly=True)
    status = fields.Selection(
        [("free", "No Rule"),
         ("ok", "Available"),
         ("near", "Almost Used Up"),
         ("reached", "Limit Reached"),
         ("over", "Over Limit")],
        readonly=True, index=True)
    product_summary = fields.Char(
        string="Products", readonly=True,
        help="What was taken that day, e.g. \"Espresso ×2, Latte ×1\".")
    order_ids = fields.Many2many("staff.allowance.order", string="Order Lines",
                                 compute="_compute_order_ids")

    # Enforced by the database, not a Python check: two requests refreshing
    # the same day at once cannot see each other's row.
    _partner_day_unique = models.UniqueIndex(
        "(partner_id, pos_category_id, day)",
        "Usage is already recorded for this contact, category and day.",
    )

    def _compute_display_name(self):
        for usage in self:
            usage.display_name = "%s - %s - %s" % (
                usage.beneficiary_name or "",
                usage.pos_category_id.display_name or "", usage.day or "")

    # ------------------------------------------------------------------
    @api.model
    def _orders_domain(self, partner, pos_category, day):
        """The orders that make up one usage row."""
        return self.env["staff.allowance.order"]._beneficiary_domain(partner) + [
            ("pos_category_id", "=", pos_category.id),
            ("order_date", "=", day),
            ("state", "in", ("draft", "done")),
        ]

    def _compute_order_ids(self):
        Order = self.env["staff.allowance.order"]
        for usage in self:
            usage.order_ids = Order.search(self._orders_domain(
                usage.partner_id, usage.pos_category_id, usage.day)) \
                if usage.partner_id and usage.pos_category_id and usage.day \
                else Order

    @api.model
    def _product_summary(self, orders):
        """"Espresso ×2, Latte ×1": what was taken, in the order it was taken."""
        quantities = {}
        for order in orders.sorted(lambda o: (o.order_datetime, o.id)):
            name = (order.product_id.with_context(display_default_code=False).display_name
                    or _("(no product)"))
            quantities[name] = quantities.get(name, 0) + order.qty
        return ", ".join(f"{name} ×{qty}" for name, qty in quantities.items())

    def action_view_orders(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "staff_allowance.action_allowance_order")
        action.update({
            "name": _("%(who)s — %(category)s, %(day)s",
                      who=self.partner_id.display_name,
                      category=self.pos_category_id.display_name, day=self.day),
            "domain": self._orders_domain(self.partner_id, self.pos_category_id,
                                          self.day),
            "context": {},
        })
        return action

    @api.model
    def _refresh(self, beneficiary, pos_category, day):
        if not beneficiary or not pos_category or not day:
            return self.browse()

        Usage = self.sudo()
        Order = self.env["staff.allowance.order"].sudo()
        Rule = self.env["staff.allowance.rule"].sudo()

        record = Usage.search(
            self._beneficiary_domain(beneficiary) + [
                ("pos_category_id", "=", pos_category.id), ("day", "=", day)
            ], limit=1)

        orders = Order.search(self._orders_domain(beneficiary, pos_category, day))
        if not orders:
            if record:
                record.unlink()
            return self.browse()

        origin, config = Rule._resolve(beneficiary, pos_category)
        count_mode = config["count_mode"] if config else "qty"
        used = (len(orders) if count_mode == "order"
                else sum(orders.mapped("qty")))

        if origin == "free":
            vals = {"used": used, "order_count": len(orders),
                    "limit_value": 0, "remaining": 0, "over_by": 0,
                    "status": "free"}
        else:
            limit = config["limit"]
            if used > limit:
                status = "over"
            elif used >= limit:
                status = "reached"
            elif limit and used >= limit * 0.8:
                status = "near"
            else:
                status = "ok"
            vals = {"used": used, "order_count": len(orders),
                    "limit_value": limit, "remaining": max(limit - used, 0),
                    "over_by": max(used - limit, 0), "status": status}

        vals["product_summary"] = self._product_summary(orders)
        if record:
            record.write(vals)
            return record
        return Usage.create({
            **self._beneficiary_vals(beneficiary),
            "pos_category_id": pos_category.id, "day": day, **vals,
        })

    @api.model
    def _refresh_keys(self, keys):
        """keys: iterable of (partner_id, pos_category_id, day)."""
        Partner = self.env["res.partner"].sudo()
        Category = self.env["pos.category"].sudo()
        for partner_id, category_id, day in keys:
            self._refresh(Partner.browse(partner_id).exists(),
                          Category.browse(category_id).exists(), day)

    @api.model
    def action_rebuild(self):
        """Rebuild every usage row from the orders. Safe to run any time."""
        Order = self.env["staff.allowance.order"].sudo()
        keys = set()
        for order in Order.search([("state", "in", ("draft", "done"))]):
            beneficiary = order._beneficiary()
            if beneficiary and order.pos_category_id and order.order_date:
                keys.add((beneficiary.id, order.pos_category_id.id,
                          order.order_date))
        self._refresh_keys(keys)
        return True
