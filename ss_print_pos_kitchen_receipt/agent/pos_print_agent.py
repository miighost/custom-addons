#!/usr/bin/env python3
"""Local ESC/POS print agent for Odoo POS.

You do NOT need this while Odoo runs on the shop LAN — the server opens the
socket itself. You WILL need it the day Odoo moves to a VPS or odoo.sh,
because a cloud server cannot reach 192.168.x.x.

Run it on the till machine (or any always-on box on the shop network):

    python3 pos_print_agent.py

Then set each printer in Odoo to transport = "Local agent on the till" with
agent URL http://127.0.0.1:8765/print.

Standard library only — no pip install, works on macOS, Windows and Linux.

Protocol:
    POST /print   {"ip": "192.168.1.50", "port": 9100, "payload_b64": "..."}
    GET  /health  -> {"ok": true}

Security: binds to the loopback interface by default, so only software on
this machine can reach it. Use --host 0.0.0.0 only on a network you control,
and pair it with --allow to restrict which printer addresses it will talk to.
"""

import argparse
import base64
import ipaddress
import json
import logging
import socket
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOG = logging.getLogger("pos_print_agent")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
PRINTER_TIMEOUT = 6.0
MAX_BODY = 2 * 1024 * 1024  # 2 MB is far more than any ticket

# Populated from --allow; empty means "any private address".
ALLOWED_PRINTERS = set()
# Origins permitted to call this agent from a browser.
ALLOWED_ORIGINS = ["*"]


def _is_private(host):
    try:
        return ipaddress.ip_address(host).is_private
    except ValueError:
        # A hostname rather than a literal address; allow it and let the
        # connection attempt decide.
        return True


def _check_target(host):
    if ALLOWED_PRINTERS:
        if host not in ALLOWED_PRINTERS:
            raise ValueError("printer %s is not in the allow list" % host)
        return
    if not _is_private(host):
        raise ValueError("refusing to connect to non-private address %s" % host)


def send_to_printer(host, port, payload):
    _check_target(host)
    sock = socket.create_connection((host, int(port)), timeout=PRINTER_TIMEOUT)
    try:
        sock.settimeout(PRINTER_TIMEOUT)
        sock.sendall(payload)
    finally:
        try:
            sock.close()
        except OSError:
            pass


class Handler(BaseHTTPRequestHandler):
    server_version = "PosPrintAgent/1.0"
    protocol_version = "HTTP/1.1"

    # -- helpers -------------------------------------------------------
    def _cors(self):
        origin = self.headers.get("Origin", "")
        allow = "*"
        if ALLOWED_ORIGINS != ["*"]:
            allow = origin if origin in ALLOWED_ORIGINS else "null"
        self.send_header("Access-Control-Allow-Origin", allow)
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "86400")
        # Chrome's Local Network Access checks look for this header when an
        # https page calls a loopback or private address.
        self.send_header("Access-Control-Allow-Private-Network", "true")

    def _reply(self, status, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        LOG.info("%s - %s", self.address_string(), fmt % args)

    # -- routes --------------------------------------------------------
    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        if self.path.rstrip("/") in ("/health", ""):
            self._reply(200, {"ok": True, "agent": self.server_version})
        else:
            self._reply(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        if self.path.rstrip("/") != "/print":
            self._reply(404, {"ok": False, "error": "not found"})
            return

        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._reply(400, {"ok": False, "error": "bad Content-Length"})
            return
        if length <= 0 or length > MAX_BODY:
            self._reply(400, {"ok": False, "error": "bad body size"})
            return

        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as err:
            self._reply(400, {"ok": False, "error": "bad JSON: %s" % err})
            return

        host = (payload.get("ip") or "").strip()
        port = payload.get("port") or 9100
        data_b64 = payload.get("payload_b64") or ""
        if not host or not data_b64:
            self._reply(400, {"ok": False, "error": "ip and payload_b64 are required"})
            return

        try:
            data = base64.b64decode(data_b64, validate=True)
        except Exception as err:
            self._reply(400, {"ok": False, "error": "bad base64: %s" % err})
            return

        try:
            send_to_printer(host, port, data)
        except ValueError as err:
            LOG.warning("rejected %s:%s — %s", host, port, err)
            self._reply(403, {"ok": False, "error": str(err)})
            return
        except OSError as err:
            LOG.warning("print to %s:%s failed — %s", host, port, err)
            self._reply(
                502,
                {"ok": False, "error": "printer unreachable: %s" % err,
                 "ip": host, "port": port},
            )
            return

        LOG.info("printed %d bytes to %s:%s", len(data), host, port)
        self._reply(200, {"ok": True, "bytes": len(data), "ip": host, "port": port})


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local ESC/POS print agent")
    parser.add_argument("--host", default=DEFAULT_HOST,
                        help="interface to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help="port to listen on (default: 8765)")
    parser.add_argument("--allow", action="append", default=[],
                        metavar="IP",
                        help="restrict to these printer addresses; repeatable")
    parser.add_argument("--origin", action="append", default=[],
                        metavar="URL",
                        help="restrict CORS to these Odoo origins; repeatable")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    global ALLOWED_PRINTERS, ALLOWED_ORIGINS
    ALLOWED_PRINTERS = set(args.allow)
    if args.origin:
        ALLOWED_ORIGINS = list(args.origin)

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    LOG.info("print agent listening on http://%s:%s", args.host, args.port)
    if ALLOWED_PRINTERS:
        LOG.info("printer allow list: %s", ", ".join(sorted(ALLOWED_PRINTERS)))
    if ALLOWED_ORIGINS != ["*"]:
        LOG.info("CORS origins: %s", ", ".join(ALLOWED_ORIGINS))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        LOG.info("shutting down")
        server.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
