# -*- coding: utf-8 -*-

from odoo import models, fields, api

class PosConfig(models.Model):
    _inherit = 'pos.config'

    kitchen_print = fields.Boolean(
        string='Show the manual "Print KOT" button',
        default=True,
        help="When off, the manual reprint button is hidden from the POS so "
             "staff cannot send duplicate tickets to the kitchen. The green "
             "Order button is unaffected.",
    )
    kitchen_print_auto = fields.Boolean(
        string='Automatic kitchen receipt printing',
        default=False,
        help="Print the kitchen ticket without anyone pressing a button.",
    )
    kitchen_print_trigger = fields.Selection(
        [
            ("on_send", "When the order is sent (leaving the order screen)"),
            ("on_payment", "At payment (when the receipt screen opens)"),
        ],
        string="Print automatically",
        default="on_send",
        required=True,
        help="on_send suits table service: the kitchen gets the ticket as soon "
             "as the waiter leaves the order screen. on_payment suits counter "
             "service, where ordering and paying are the same step.",
    )

    @api.onchange('module_pos_restaurant')
    def _onchange_module_pos_restaurant(self):
        if not getattr(self, 'module_pos_restaurant', False):
            self.kitchen_print_auto = False
            self.kitchen_print = False

    @api.onchange('is_order_printer')
    def _onchange_is_order_printer(self):
        if hasattr(self, 'is_order_printer') and not getattr(self, 'is_order_printer', False):
            self.kitchen_print = False

    def _ss_kitchen_settings(self):
        """The settings the POS front-end needs, read straight off the record.

        Deliberately not routed through the POS data-loading machinery: whether
        a custom pos.config field reaches the browser depends on internals that
        differ between versions. The front-end fetches this over the same RPC
        it already uses for the printer list.
        """
        self.ensure_one()
        return {
            "kitchen_print": bool(self.kitchen_print),
            "kitchen_print_auto": bool(self.kitchen_print_auto),
            "kitchen_print_trigger": self.kitchen_print_trigger or "on_send",
        }

    # NOTE: there was a _load_pos_data_fields() override here that tried to
    # also ship these fields inside the POS bundle. It broke POS startup with
    # "Cannot read properties of undefined (reading 'currency_id')" in
    # processServerData: interfering with the POS data-loading field list
    # disturbs how the loader builds its records.
    #
    # It was never needed. The front-end reads these settings over the same
    # RPC it uses for the printer list (ss.escpos.printer.load_setup), which
    # depends on nothing version-specific. Do not add it back.


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    kitchen_print = fields.Boolean(related='pos_config_id.kitchen_print', readonly=False)
    kitchen_print_auto = fields.Boolean(related='pos_config_id.kitchen_print_auto', readonly=False)
    kitchen_print_trigger = fields.Selection(
        related='pos_config_id.kitchen_print_trigger', readonly=False
    )

    @api.onchange('pos_module_pos_restaurant')
    def _onchange_pos_module_pos_restaurant(self):
        if hasattr(self, 'pos_module_pos_restaurant') and not getattr(self, 'pos_module_pos_restaurant', False):
            self.kitchen_print_auto = False
            self.kitchen_print = False

    @api.onchange('pos_is_order_printer')
    def _onchange_pos_is_order_printer(self):
        if hasattr(self, 'pos_is_order_printer') and not getattr(self, 'pos_is_order_printer', False):
            self.kitchen_print = False


import logging
import threading
import odoo

_logger = logging.getLogger(__name__)

PAID_STATES = ("paid", "done", "invoiced")


class PosOrder(models.Model):
    _inherit = 'pos.order'

    backend_kot_printed = fields.Boolean(
        string="Backend KOT Printed",
        default=False,
        copy=False,
        help="Tracks whether this order was automatically printed to LAN kitchen printers by the backend."
    )

    @api.model_create_multi
    def create(self, vals_list):
        orders = super().create(vals_list)
        for order in orders:
            if not self.env.context.get('pos_ui_print_in_flight'):
                order._auto_print_kot_async()
        return orders

    def write(self, vals):
        res = super().write(vals)
        if any(f in vals for f in ("state", "lines", "payment_ids", "amount_paid")):
            for order in self:
                if not self.env.context.get('pos_ui_print_in_flight'):
                    if order.state in PAID_STATES or not order.backend_kot_printed:
                        order._auto_print_kot_async()
        return res

    def action_pos_order_paid(self):
        res = super().action_pos_order_paid()
        for order in self:
            if not self.env.context.get('pos_ui_print_in_flight'):
                order._auto_print_kot_async(force=True)
        return res

    def _process_order(self, order, existing_order):
        order_id = super()._process_order(order, existing_order)
        if order_id:
            pos_order = self.env["pos.order"].browse(order_id)
            if pos_order.exists() and not self.env.context.get('pos_ui_print_in_flight'):
                pos_order._auto_print_kot_async()
        return order_id

    def _auto_print_kot_async(self, force=False):
        """Asynchronously dispatches raw ESC/POS KOT to LAN printers without blocking HTTP request."""
        for order in self:
            if not order.lines:
                continue
            if order.backend_kot_printed and not force:
                continue
            order_id = order.id
            db_name = self.env.cr.dbname
            uid = self.env.uid

            def _worker():
                try:
                    registry = odoo.registry(db_name)
                    with registry.cursor() as cr:
                        env = api.Environment(cr, uid, {})
                        ord_rec = env['pos.order'].browse(order_id)
                        if ord_rec.exists() and ord_rec.lines:
                            sent = env['ss.escpos.printer'].print_order_kot(ord_rec)
                            if sent > 0:
                                ord_rec.sudo().write({'backend_kot_printed': True})
                except Exception as ex:
                    _logger.warning("Async KOT print failed for pos.order %s: %s", order_id, ex)

            threading.Thread(target=_worker, daemon=True).start()


class PosOrderLine(models.Model):
    _inherit = 'pos.order.line'

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        if not self.env.context.get('pos_ui_print_in_flight'):
            orders = lines.mapped('order_id')
            for order in orders:
                order._auto_print_kot_async()
        return lines

    def write(self, vals):
        res = super().write(vals)
        if any(f in vals for f in ("qty", "note", "customer_note", "price_unit", "product_id")):
            if not self.env.context.get('pos_ui_print_in_flight'):
                orders = self.mapped("order_id")
                for order in orders:
                    order._auto_print_kot_async()
        return res


class PosPayment(models.Model):
    _inherit = 'pos.payment'

    @api.model_create_multi
    def create(self, vals_list):
        payments = super().create(vals_list)
        if not self.env.context.get('pos_ui_print_in_flight'):
            orders = payments.mapped('pos_order_id')
            for order in orders:
                order._auto_print_kot_async(force=True)
        return payments




