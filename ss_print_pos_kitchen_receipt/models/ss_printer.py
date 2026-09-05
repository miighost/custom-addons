# -*- coding: utf-8 -*-
"""Network ESC/POS printers for the POS, with a swappable transport.

Two transports, one renderer:

  server_socket  The Odoo server opens a TCP socket to the printer on port
                 9100 and writes the bytes.  Requires the Odoo server to sit
                 on the same LAN as the printers.  Use this while Odoo runs
                 on a local box.

  browser_agent  The server only renders; the POS browser fetches the bytes
                 and POSTs them to a small agent on the till
                 (127.0.0.1:8765), which owns the socket.  Use this once
                 Odoo moves to a VPS / odoo.sh and can no longer reach
                 192.168.x.x.

Switching between them is one field on the printer record.  Nothing else in
the module changes, because both paths call the same render_ticket().
"""

import base64
import logging
import socket

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .escpos import render_kot

_logger = logging.getLogger(__name__)

DEFAULT_PORT = 9100


class SsEscposPrinter(models.Model):
    _name = "ss.escpos.printer"
    _description = "POS Network ESC/POS Printer"
    _order = "sequence, id"

    name = fields.Char(required=True, help="Label shown in the POS, e.g. 'Kitchen', 'Bar 2'.")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    ip = fields.Char(
        string="IP address",
        required=True,
        help="LAN address of the printer, e.g. 192.168.1.50.",
    )
    port = fields.Integer(default=DEFAULT_PORT, required=True)

    transport = fields.Selection(
        [
            ("server_socket", "Odoo server opens the socket (server on the same LAN)"),
            ("browser_agent", "Local agent on the till (Odoo hosted off-site)"),
        ],
        default="server_socket",
        required=True,
        string="Transport",
    )
    agent_url = fields.Char(
        string="Agent URL",
        default="http://127.0.0.1:8765/print",
        help="Only used with the 'Local agent' transport. The POS browser "
             "posts the rendered ticket here.",
    )

    paper_width = fields.Selection(
        [("48", "80 mm (48 characters)"), ("32", "58 mm (32 characters)")],
        default="48",
        required=True,
        string="Paper width",
    )
    codepage = fields.Char(
        default="cp437",
        required=True,
        help="Character encoding the printer expects. cp437 suits most "
             "generic units; try cp850 or cp1252 for accented characters.",
    )
    station_label = fields.Char(
        string="Header",
        help="Printed in large type at the top of every ticket. "
             "Defaults to the printer name.",
    )

    # -- live status ---------------------------------------------------
    status = fields.Selection(
        [
            ("unknown", "Not checked"),
            ("online", "Online"),
            ("offline", "Unreachable"),
        ],
        default="unknown",
        readonly=True,
        string="Status",
    )
    last_seen = fields.Datetime(readonly=True, string="Last reached")
    last_error = fields.Char(readonly=True, string="Last error")
    last_print = fields.Datetime(readonly=True, string="Last ticket sent")

    pos_config_ids = fields.Many2many(
        "pos.config",
        string="Points of Sale",
        help="Leave empty to use this printer on every POS.",
    )
    product_category_ids = fields.Many2many(
        "pos.category",
        string="POS categories",
        help="Only order lines in these categories are sent to this printer. "
             "Leave empty to send every line.",
    )

    # ------------------------------------------------------------------
    # Status bookkeeping
    # ------------------------------------------------------------------
    def _set_status(self, vals):
        """Persist status on a separate cursor.

        Raising UserError rolls the transaction back, which would discard a
        plain write() made just before it. Printer status is diagnostic
        information we want to keep precisely when the print failed, so it
        is committed independently.
        """
        if not self:
            return
        try:
            with self.env.registry.cursor() as cr:
                env = self.env(cr=cr, su=True)
                env["ss.escpos.printer"].browse(self.ids).write(vals)
        except Exception:  # never let bookkeeping break printing
            _logger.exception("Could not record printer status for %s", self.ids)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def _render_bytes(self, data):
        self.ensure_one()
        return render_kot(
            data or {},
            width=int(self.paper_width or 48),
            codepage=self.codepage or "cp437",
            station=self.station_label or self.name,
        )

    @api.model
    def load_printers(self, pos_config_id=None):
        """Return the printer set the POS front-end should know about."""
        domain = [("active", "=", True)]
        printers = self.search(domain)
        if pos_config_id:
            printers = printers.filtered(
                lambda p: not p.pos_config_ids or pos_config_id in p.pos_config_ids.ids
            )
        return [
            {
                "id": p.id,
                "name": p.name,
                "transport": p.transport,
                "agent_url": p.agent_url or "",
                "ip": p.ip,
                "port": p.port or DEFAULT_PORT,
                "category_ids": p.product_category_ids.ids,
                "station_label": p.station_label or p.name,
            }
            for p in printers
        ]

    @api.model
    def render_ticket(self, printer_id, data):
        """Render only. Used by the browser_agent transport.

        Returns base64 so the payload survives the JSON-RPC round trip.
        """
        printer = self.browse(printer_id).exists()
        if not printer:
            raise UserError(_("Printer %s no longer exists.") % printer_id)
        payload = printer._render_bytes(data)
        return {
            "printer_id": printer.id,
            "name": printer.name,
            "ip": printer.ip,
            "port": printer.port or DEFAULT_PORT,
            "agent_url": printer.agent_url or "",
            "payload_b64": base64.b64encode(payload).decode("ascii"),
        }

    # ------------------------------------------------------------------
    # Transport: server-side socket
    # ------------------------------------------------------------------
    def _send_socket(self, payload, timeout=6.0):
        self.ensure_one()
        host = (self.ip or "").strip()
        port = self.port or DEFAULT_PORT
        if not host:
            raise UserError(_("Printer '%s' has no IP address.") % self.name)

        sock = None
        try:
            sock = socket.create_connection((host, port), timeout=timeout)
            sock.settimeout(timeout)
            sock.sendall(payload)
        except OSError as err:
            # Surface the real reason. Silent failure is what made the
            # previous implementation impossible to debug.
            _logger.warning(
                "ESC/POS print to %s (%s:%s) failed: %s", self.name, host, port, err
            )
            self._set_status({"status": "offline", "last_error": str(err)[:200]})
            raise UserError(
                _("Could not reach printer '%(name)s' at %(host)s:%(port)s.\n%(err)s")
                % {"name": self.name, "host": host, "port": port, "err": err}
            ) from err
        else:
            now = fields.Datetime.now()
            self._set_status({
                "status": "online",
                "last_seen": now,
                "last_print": now,
                "last_error": False,
            })
        finally:
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
        return True

    @api.model
    def print_ticket(self, printer_id, data):
        """Render and send from the server. Used by the server_socket transport."""
        printer = self.browse(printer_id).exists()
        if not printer:
            raise UserError(_("Printer %s no longer exists.") % printer_id)
        payload = printer._render_bytes(data)
        printer._send_socket(payload)
        _logger.info(
            "ESC/POS ticket sent to %s (%s:%s), %d bytes",
            printer.name, printer.ip, printer.port, len(payload),
        )
        return {"ok": True, "printer_id": printer.id, "bytes": len(payload)}

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------
    def action_test_print(self):
        """Button on the printer form: prove the wiring end to end."""
        sent = []
        for printer in self:
            if printer.transport != "server_socket":
                raise UserError(_(
                    "Printer '%s' uses the local-agent transport, so the test "
                    "must run from the POS screen — the browser owns that "
                    "connection, not the server."
                ) % printer.name)
            sample = {
                "name": "TEST-0001",
                "datetime": fields.Datetime.to_string(fields.Datetime.now()),
                "table_name": "T1",
                "floor_name": "Test",
                "cashier": self.env.user.name,
                "print_label": "Test print",
                "orderlines": [
                    {"qty": "2", "product_name": "Test Item",
                     "attribute_values": "", "note": "no onions"},
                    {"qty": "1", "product_name": "Second Test Item",
                     "attribute_values": "", "note": ""},
                ],
                "general_note": "If you can read this, the printer is wired correctly.",
            }
            printer._send_socket(printer._render_bytes(sample))
            _logger.info("Test ticket sent to %s", printer.name)
            sent.append(printer.name)

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Test print sent"),
                "message": _("Sent to: %s. Check the paper.") % ", ".join(sent),
                "type": "success",
                "next": {"type": "ir.actions.act_window_close"},
            },
        }

    def action_probe(self):
        """Check the TCP port without sending anything to print."""
        import socket as _socket
        reached, failed = [], []
        for printer in self:
            host = (printer.ip or "").strip()
            port = printer.port or DEFAULT_PORT
            try:
                sock = _socket.create_connection((host, port), timeout=4.0)
                sock.close()
            except OSError as err:
                printer.write({"status": "offline", "last_error": str(err)[:200]})
                failed.append("%s (%s:%s) - %s" % (printer.name, host, port, err))
            else:
                printer.write({
                    "status": "online",
                    "last_seen": fields.Datetime.now(),
                    "last_error": False,
                })
                reached.append("%s (%s:%s)" % (printer.name, host, port))

        lines = []
        if reached:
            lines.append(_("Online: %s") % ", ".join(reached))
        if failed:
            lines.append(_("Unreachable: %s") % "; ".join(failed))

        # Returned as a notification rather than raised: a UserError would
        # roll back the status we just wrote.
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Printer probe"),
                "message": "\n".join(lines) or _("Nothing to probe."),
                "type": "danger" if failed else "success",
                "sticky": bool(failed),
                "next": {"type": "ir.actions.act_window_close"},
            },
        }

    @api.model
    def action_probe_all(self):
        """Server action: refresh the status column for every printer."""
        self.search([]).action_probe()
        return True

    def action_open_scan(self):
        """Open the discovery wizard from the printer list."""
        return {
            "type": "ir.actions.act_window",
            "name": _("Scan network for printers"),
            "res_model": "ss.escpos.printer.scan",
            "view_mode": "form",
            "target": "new",
        }
