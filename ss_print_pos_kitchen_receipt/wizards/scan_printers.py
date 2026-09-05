# -*- coding: utf-8 -*-
"""Find printers on the LAN and test them before committing to a record."""

import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..models.escpos import render_kot
from . import netscan

_logger = logging.getLogger(__name__)


class SsPrinterScan(models.TransientModel):
    _name = "ss.escpos.printer.scan"
    _description = "Scan the network for printers"

    target = fields.Char(
        string="Addresses to scan",
        required=True,
        default=lambda self: netscan.local_subnet_guess(),
        help="A subnet (192.168.1.0/24), a range (192.168.1.10-60), a single "
             "address, or several separated by commas.",
    )
    timeout = fields.Float(
        string="Timeout per port (s)",
        default=0.4,
        required=True,
        help="Raise this on a slow or congested network. 0.4s suits most LANs.",
    )
    scan_raw = fields.Boolean(string="Raw ESC/POS (9100)", default=True)
    scan_http = fields.Boolean(string="HTTP / ePOS (80)", default=True)
    scan_ipp = fields.Boolean(string="IPP (631)", default=False)
    scan_lpd = fields.Boolean(string="LPD (515)", default=False)

    line_ids = fields.One2many(
        "ss.escpos.printer.scan.line", "scan_id", string="Devices found"
    )
    state = fields.Selection(
        [("draft", "Draft"), ("done", "Done")], default="draft"
    )
    summary = fields.Char(readonly=True)

    def _ports(self):
        self.ensure_one()
        ports = []
        if self.scan_raw:
            ports.append(netscan.PORT_RAW)
        if self.scan_http:
            ports.append(netscan.PORT_HTTP)
        if self.scan_ipp:
            ports.append(netscan.PORT_IPP)
        if self.scan_lpd:
            ports.append(netscan.PORT_LPD)
        if not ports:
            raise UserError(_("Select at least one port to scan."))
        return tuple(ports)

    def action_scan(self):
        self.ensure_one()
        try:
            targets = netscan.parse_targets(self.target)
        except ValueError as err:
            raise UserError(_("Could not read the address list.\n%s") % err) from err
        if not targets:
            raise UserError(_("No addresses to scan."))

        _logger.info("Printer scan: %d addresses, ports %s", len(targets), self._ports())
        findings = netscan.sweep(
            targets, ports=self._ports(), timeout=max(0.1, self.timeout or 0.4)
        )

        known = {p.ip: p for p in self.env["ss.escpos.printer"].search([])}
        self.line_ids.unlink()

        values = []
        for found in findings:
            existing = known.get(found["host"])
            values.append({
                "scan_id": self.id,
                "ip": found["host"],
                "ports": ", ".join(str(p) for p in found["open_ports"]),
                "kind": found["kind"],
                "confidence": found["confidence"],
                "escpos_verified": found["escpos_verified"],
                "device_name": found["banner_name"] or "",
                "existing_printer_id": existing.id if existing else False,
                # Pre-tick the ones that look like raw ESC/POS and are not
                # already registered.
                "selected": bool(
                    found["kind"] == "escpos" and not existing
                ),
                "name": found["banner_name"] or _("Printer %s") % found["host"].rsplit(".", 1)[-1],
            })
        self.env["ss.escpos.printer.scan.line"].create(values)

        escpos_count = sum(1 for f in findings if f["kind"] == "escpos")
        self.state = "done"
        self.summary = _(
            "%(scanned)d addresses scanned — %(found)d devices answered, "
            "%(escpos)d look like ESC/POS printers."
        ) % {"scanned": len(targets), "found": len(findings), "escpos": escpos_count}

        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
            "context": self.env.context,
        }

    def action_import(self):
        self.ensure_one()
        chosen = self.line_ids.filtered(lambda l: l.selected and not l.existing_printer_id)
        if not chosen:
            raise UserError(_("Tick at least one new device to add."))
        printers = self.env["ss.escpos.printer"]
        for line in chosen:
            printers |= printers.create({
                "name": line.name or line.ip,
                "ip": line.ip,
                "port": netscan.PORT_RAW,
                "transport": "server_socket",
            })
        return {
            "type": "ir.actions.act_window",
            "name": _("Network Printers"),
            "res_model": "ss.escpos.printer",
            "view_mode": "list,form",
            "domain": [("id", "in", printers.ids)],
        }


class SsPrinterScanLine(models.TransientModel):
    _name = "ss.escpos.printer.scan.line"
    _description = "Device found by the printer scan"
    _order = "ip"

    scan_id = fields.Many2one("ss.escpos.printer.scan", required=True, ondelete="cascade")
    selected = fields.Boolean(string="Add")
    ip = fields.Char(required=True, readonly=True)
    name = fields.Char(string="Name to use")
    device_name = fields.Char(string="Reported as", readonly=True)
    ports = fields.Char(string="Open ports", readonly=True)
    kind = fields.Selection(
        [
            ("escpos", "Raw ESC/POS"),
            ("epos", "Epson ePOS"),
            ("other", "Other printer service"),
            ("unknown", "Unidentified"),
        ],
        readonly=True,
    )
    confidence = fields.Selection(
        [("high", "High"), ("medium", "Medium"), ("low", "Low")], readonly=True
    )
    escpos_verified = fields.Boolean(
        string="Answered status query", readonly=True,
        help="The device replied to a non-printing ESC/POS status request, "
             "which is strong evidence it is a real ESC/POS printer.",
    )
    existing_printer_id = fields.Many2one(
        "ss.escpos.printer", string="Already registered", readonly=True
    )

    def action_test_print(self):
        """Send a sample ticket straight to this address, before saving it."""
        self.ensure_one()
        payload = render_kot(
            {
                "name": "SCAN-TEST",
                "datetime": fields.Datetime.to_string(fields.Datetime.now()),
                "table_name": self.ip.rsplit(".", 1)[-1],
                "cashier": self.env.user.name,
                "print_label": "Discovery test print",
                "orderlines": [
                    {"qty": "1", "product_name": "Test line one", "note": ""},
                    {"qty": "2", "product_name": "Test line two", "note": "with a note"},
                ],
                "general_note": "Printed from the Odoo network scan at %s." % self.ip,
            },
            width=48,
            station="TEST",
        )

        import socket as _socket
        try:
            sock = _socket.create_connection((self.ip, netscan.PORT_RAW), timeout=6.0)
        except OSError as err:
            raise UserError(
                _("Could not reach %(ip)s:9100 — %(err)s")
                % {"ip": self.ip, "err": err}
            ) from err
        try:
            sock.sendall(payload)
        except OSError as err:
            raise UserError(
                _("Connected to %(ip)s but the write failed — %(err)s")
                % {"ip": self.ip, "err": err}
            ) from err
        finally:
            try:
                sock.close()
            except OSError:
                pass

        # Notification, not UserError: raising would roll back the wizard
        # lines the user is in the middle of ticking.
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Test sent to %s") % self.ip,
                "message": _(
                    "Sent %d bytes. If paper came out, this is a working "
                    "ESC/POS printer — tick Add and import it."
                ) % len(payload),
                "type": "success",
                "sticky": False,
            },
        }
