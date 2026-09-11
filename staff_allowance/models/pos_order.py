from odoo import _, api, fields, models


class PosOrder(models.Model):
    """Bridge between real POS sales and the allowance ledger.

    A POS sale is a fact that already happened, so consumption is ALWAYS
    recorded here, even when it puts the customer over their limit. The
    over-limit flag is what surfaces it in the monitoring views. Blocking
    belongs at the point of ordering (the app, or the POS screen warning),
    not at the point of recording.
    """

    _inherit = "pos.order"

    allowance_recorded = fields.Boolean(copy=False, readonly=True)
    allowance_over_limit = fields.Boolean(string="Over Allowance", copy=False,
                                          readonly=True, index=True)
    allowance_order_ids = fields.One2many("staff.allowance.order", "pos_order_id",
                                          string="Allowance Entries")

    @api.model_create_multi
    def create(self, vals_list):
        orders = super().create(vals_list)
        orders._record_allowance()
        return orders

    def write(self, vals):
        result = super().write(vals)
        if self.env.context.get("skip_allowance_record"):
            return result
        # The customer or the lines changing means the ledger has to be redone.
        if {"partner_id", "lines"} & set(vals):
            self._record_allowance(force=True)
        elif "state" in vals:
            self._record_allowance()
        return result

    # ------------------------------------------------------------------
    def _record_allowance(self, force=False):
        Allowance = self.env["staff.allowance.order"].sudo()
        Rule = self.env["staff.allowance.rule"].sudo()

        for order in self:
            if order.allowance_recorded and not force:
                continue

            previous = Allowance.search([("pos_order_id", "=", order.id)])
            if not order.partner_id:
                # No customer on the ticket: nobody's allowance to charge.
                if previous:
                    previous.unlink()
                if order.allowance_recorded:
                    order.with_context(skip_allowance_record=True).write({
                        "allowance_recorded": False,
                        "allowance_over_limit": False,
                    })
                continue

            if previous:
                previous.unlink()

            over_limit = False
            for line in order.lines:
                qty = int(round(line.qty or 0))
                if qty <= 0:
                    # Refund and zero lines do not consume an allowance.
                    continue
                category = Rule._category_of_product(line.product_id)
                if not category:
                    continue
                entry = Allowance.with_context(allowance_force=True).create({
                    "partner_id": order.partner_id.id,
                    "pos_category_id": category.id,
                    "product_id": line.product_id.id,
                    "qty": qty,
                    "source": "pos",
                    "state": "done",
                    "pos_order_id": order.id,
                    "order_datetime": order.date_order or fields.Datetime.now(),
                })
                over_limit = over_limit or entry.is_over_limit

            order.with_context(skip_allowance_record=True).write({
                "allowance_recorded": True,
                "allowance_over_limit": over_limit,
            })

    # ------------------------------------------------------------------
    def action_view_allowance_entries(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Allowance Entries"),
            "res_model": "staff.allowance.order",
            "view_mode": "list,form",
            "domain": [("pos_order_id", "=", self.id)],
        }
