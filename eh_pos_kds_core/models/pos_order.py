import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

PAID_STATES = ("paid", "done", "invoiced")



class PosOrder(models.Model):
    """Intake seam from POS into the kitchen.

    When an order reaches a paid state or is created via external APIs/mobile apps,
    it is routed to the matching boards. The intake diffs the order lines against
    what the kitchen already knows, keyed by the order line uuid, so re syncs never
    duplicate and removed quantity is absorbed and voided rather than deleted.
    """

    _inherit = "pos.order"

    @api.model_create_multi
    def create(self, vals_list):
        orders = super().create(vals_list)
        for order in orders:
            if order.lines:
                try:
                    order.sudo()._eh_kds_intake()
                except Exception:
                    _logger.exception("eh_pos_kds: API create intake failed for pos.order %s", order.id)
        return orders

    def write(self, vals):
        res = super().write(vals)
        if any(f in vals for f in ("state", "lines", "table_id", "partner_id")):
            for order in self:
                if order.lines:
                    try:
                        order.sudo()._eh_kds_intake()
                    except Exception:
                        _logger.exception("eh_pos_kds: API write intake failed for pos.order %s", order.id)
        return res

    def action_pos_order_paid(self):
        res = super().action_pos_order_paid()
        for order in self:
            if order.lines:
                try:
                    order.sudo()._eh_kds_intake()
                except Exception:
                    _logger.exception("eh_pos_kds: action_pos_order_paid intake failed for pos.order %s", order.id)
        return res

    def _process_order(self, order, existing_order):
        order_id = super()._process_order(order, existing_order)
        pos_order = self.env["pos.order"].browse(order_id)
        if pos_order and pos_order.state in PAID_STATES:
            try:
                pos_order.sudo()._eh_kds_intake()
            except Exception:
                # A kitchen routing problem must never block a sale.
                _logger.exception("eh_pos_kds: intake failed for pos.order %s", order_id)
        return order_id


    def _eh_kds_ref(self):
        self.ensure_one()
        return self.tracking_number or self.pos_reference or self.name or str(self.id)

    # -- extension seams (used by the restaurant and self-order add-ons) ------

    def _eh_kds_routable_lines(self):
        """Lines that should be routed to the kitchen. Default: all lines.
        The restaurant add-on narrows this to lines whose course is fired.
        """
        self.ensure_one()
        return self.lines

    def _eh_kds_ticket_vals(self):
        """Extra values for the ticket on create (e.g. the restaurant table)."""
        return {}

    def _eh_kds_item_vals(self, line):
        """Extra values for a ticket item on create (e.g. the course)."""
        return {}

    def _eh_kds_intake(self, options=None):
        """Route this order's new and removed lines to the kitchen boards."""
        self.ensure_one()
        Board = self.env["eh.kds.board"].sudo()
        Ticket = self.env["eh.kds.ticket"].sudo()
        Item = self.env["eh.kds.ticket.item"].sudo()
        Card = self.env["eh.kds.card"].sudo()

        if not Board.search_count([("active", "=", True)]):
            return Ticket

        ticket = Ticket.search([("pos_order_id", "=", self.id)], limit=1)
        if not ticket:
            ticket = Ticket.create(
                dict({"pos_order_id": self.id, "ticket_ref": self._eh_kds_ref()}, **self._eh_kds_ticket_vals())
            )

        touched = self.env["eh.kds.board"].sudo()
        for line in self._eh_kds_routable_lines():
            line_uuid = getattr(line, "uuid", False) or str(line.id)
            items = ticket.item_ids.filtered(lambda i, lu=line_uuid: i.pos_order_line_uuid == lu)
            known = sum(i.quantity - i.cancelled for i in items)
            delta = line.qty - known
            if delta > 0:
                attr_value_ids = line.product_id.product_template_attribute_value_ids.ids if hasattr(line.product_id, "product_template_attribute_value_ids") else []

                # Reuse existing active item for this line_uuid if present
                existing_item = items[0] if items else False

                if existing_item:
                    existing_item.quantity += delta
                    for card in existing_item.card_ids.filtered(lambda c: c.status != "voided"):
                        card._log("updated", push=False)
                        touched |= card.board_id
                else:
                    item = Item.create(
                        dict(
                            {
                                "ticket_id": ticket.id,
                                "product_id": line.product_id.id,
                                "quantity": delta,
                                "pos_order_line_id": line.id,
                                "pos_order_line_uuid": line_uuid,
                                "customer_note": getattr(line, "customer_note", False) or getattr(line, "note", False),
                                "note": getattr(line, "note", False),
                                "attribute_value_ids": [(6, 0, attr_value_ids)],
                            },
                            **self._eh_kds_item_vals(line),
                        )
                    )
                    for board, lane in Board._route_item(self.config_id, line.product_id, attr_value_ids):
                        card = Card.create({"item_id": item.id, "lane_id": lane.id})
                        card._log("placed", to_lane=lane, push=False)
                        touched |= board

            elif delta < 0 and items:
                remaining_to_cancel = -delta
                for item in items.sorted("id", reverse=True):
                    if remaining_to_cancel <= 0:
                        break
                    active_qty = item.quantity - item.cancelled
                    if active_qty <= 0:
                        continue
                    cancel_amount = min(active_qty, remaining_to_cancel)
                    item.cancelled += cancel_amount
                    remaining_to_cancel -= cancel_amount
                    if (item.quantity - item.cancelled) <= 0:
                        for card in item.card_ids.filtered(lambda c: c.status != "voided"):
                            card._log("voided", push=False)
                            touched |= card.board_id

        for board in touched:
            board._kds_push(
                board.access_token,
                "kds.ticket",
                {"ticket_id": ticket.id, "ticket_ref": ticket.ticket_ref, "event": "intake"},
            )
            board._kds_push(board.access_token, "kds.status", {"ticket_ref": ticket.ticket_ref})
        return ticket


class PosOrderLine(models.Model):
    _inherit = "pos.order.line"

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        orders = lines.mapped("order_id")
        for order in orders:
            try:
                order.sudo()._eh_kds_intake()
            except Exception:
                _logger.exception("eh_pos_kds: line create intake failed for pos.order %s", order.id)
        return lines

    def write(self, vals):
        res = super().write(vals)
        if any(f in vals for f in ("qty", "note", "customer_note", "price_unit", "product_id")):
            orders = self.mapped("order_id")
            for order in orders:
                try:
                    order.sudo()._eh_kds_intake()
                except Exception:
                    _logger.exception("eh_pos_kds: line write intake failed for pos.order %s", order.id)
        return res

