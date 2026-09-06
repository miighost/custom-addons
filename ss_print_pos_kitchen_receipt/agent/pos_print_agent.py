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
    POST /print    {"ip": "192.168.1.50", "port": 9100, "payload_b64": "..."}
    POST /print    {"printer_name": "XP-58", "payload_b64": "..."}   (USB)
    GET  /printers -> the local printers this machine can see
    GET  /health   -> {"ok": true}

USB printers are addressed by the name the operating system knows them by.
On Windows the bytes go out through the RAW datatype, bypassing the driver's
page rendering, which is what a thermal printer wants. That uses pywin32 when
it is installed; when it is not — an offline till, say — the same raw bytes go
through the printer's Windows share with `copy /b`, which needs nothing
installed at all. On macOS and Linux the same is done with `lp -o raw`.

Security: binds to the loopback interface by default, so only software on
this machine can reach it. Use --host 0.0.0.0 only on a network you control,
and pair it with --allow to restrict which printer addresses it will talk to.
"""

import argparse
import base64
import ipaddress
import json
import logging
import os
import socket
import subprocess
import sys
import tempfile
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


def _win_powershell(script, timeout=10):
    """Run a PowerShell one-liner. Present on every supported Windows."""
    return subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, timeout=timeout,
    )


def list_local_printers():
    """Names of printers this machine can see. Best effort, never raises."""
    if sys.platform.startswith("win"):
        # Preferred: pywin32, if it happens to be installed.
        try:
            import win32print
        except ImportError:
            win32print = None

        if win32print is not None:
            try:
                flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
                names = [p[2] for p in win32print.EnumPrinters(flags)]
                default = ""
                try:
                    default = win32print.GetDefaultPrinter()
                except Exception:
                    pass
                return {"available": True, "backend": "win32print",
                        "printers": names, "default": default}
            except Exception as err:
                return {"available": False, "backend": "win32print",
                        "error": str(err), "printers": []}

        # No pywin32 and no internet to install it: PowerShell ships with
        # Windows and can list printers, including their share names, which
        # is what the share-based raw printing path needs.
        try:
            out = _win_powershell(
                "Get-Printer | Select-Object Name,ShareName,Shared | ConvertTo-Json -Compress"
            )
            if out.returncode == 0 and out.stdout.strip():
                data = json.loads(out.stdout)
                if isinstance(data, dict):
                    data = [data]
                printers = [d.get("Name") for d in data if d.get("Name")]
                shared = {
                    d.get("Name"): d.get("ShareName")
                    for d in data
                    if d.get("Shared") and d.get("ShareName")
                }
                return {"available": True, "backend": "powershell",
                        "printers": printers, "shared": shared,
                        "note": "pywin32 not installed; raw printing uses the "
                                "printer's Windows share. Share the bill "
                                "printer and use its share name."}
            return {"available": False, "backend": "powershell",
                    "error": (out.stderr or "Get-Printer returned nothing").strip(),
                    "printers": []}
        except Exception as err:
            return {"available": False, "backend": "powershell",
                    "error": str(err), "printers": []}

    try:
        out = subprocess.run(
            ["lpstat", "-a"], capture_output=True, text=True, timeout=5
        )
        names = [line.split()[0] for line in out.stdout.splitlines() if line.strip()]
        return {"available": True, "backend": "cups", "printers": names}
    except Exception as err:
        return {"available": False, "backend": "cups",
                "error": str(err), "printers": []}


def _win_send_via_win32print(printer_name, payload, job_name):
    import win32print

    handle = win32print.OpenPrinter(printer_name)
    try:
        # RAW hands the bytes straight to the device: no driver page
        # rendering, so ESC/POS cut and drawer commands survive intact.
        win32print.StartDocPrinter(handle, 1, (job_name, None, "RAW"))
        try:
            win32print.StartPagePrinter(handle)
            win32print.WritePrinter(handle, payload)
            win32print.EndPagePrinter(handle)
        finally:
            win32print.EndDocPrinter(handle)
    finally:
        win32print.ClosePrinter(handle)


def _win_send_via_share(printer_name, payload):
    """Raw printing with nothing installed, using the printer's share.

    Windows copies a file byte-for-byte to a shared printer, which is exactly
    what a thermal printer needs. `printer_name` here may be either the share
    name (resolved against this machine) or a full UNC path.
    """
    if printer_name.startswith("\\\\"):
        target = printer_name
    else:
        host = os.environ.get("COMPUTERNAME") or "localhost"
        target = "\\\\%s\\%s" % (host, printer_name)

    handle, temp_path = tempfile.mkstemp(prefix="pos_bill_", suffix=".prn")
    try:
        with os.fdopen(handle, "wb") as fh:
            fh.write(payload)
        # copy /b is a cmd builtin, hence the shell invocation.
        proc = subprocess.run(
            ["cmd", "/c", "copy", "/b", temp_path, target],
            capture_output=True, text=True, timeout=20,
        )
        if proc.returncode != 0:
            raise OSError(
                "copy to %s failed: %s"
                % (target, (proc.stderr or proc.stdout or "").strip()
                   or "exit code %s" % proc.returncode)
            )
    finally:
        try:
            os.unlink(temp_path)
        except OSError:
            pass


def send_to_local_printer(printer_name, payload, job_name="Odoo POS"):
    """Write raw ESC/POS bytes to a printer attached to this machine."""
    if not printer_name:
        raise ValueError("no local printer name given")

    if sys.platform.startswith("win"):
        try:
            import win32print  # noqa: F401
        except ImportError:
            # No third-party package, no internet needed: go through the
            # printer's Windows share instead.
            LOG.debug("pywin32 absent; printing %r via its Windows share",
                      printer_name)
            _win_send_via_share(printer_name, payload)
            return
        _win_send_via_win32print(printer_name, payload, job_name)
        return

    # macOS / Linux: CUPS, raw so the driver does not reformat the stream.
    proc = subprocess.run(
        ["lp", "-d", printer_name, "-o", "raw", "-t", job_name, "-"],
        input=payload, capture_output=True, timeout=20,
    )
    if proc.returncode != 0:
        raise OSError(
            "lp exited %s: %s"
            % (proc.returncode, (proc.stderr or b"").decode("utf-8", "replace").strip())
        )


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
        route = self.path.rstrip("/")
        if route in ("/health", ""):
            self._reply(200, {"ok": True, "agent": self.server_version,
                              "platform": sys.platform})
        elif route == "/printers":
            # Setup aid: shows the exact names to type into Odoo's
            # "Local printer name" field.
            self._reply(200, {"ok": True, **list_local_printers()})
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
        printer_name = (payload.get("printer_name") or "").strip()
        data_b64 = payload.get("payload_b64") or ""

        if not data_b64:
            self._reply(400, {"ok": False, "error": "payload_b64 is required"})
            return
        if not host and not printer_name:
            self._reply(
                400,
                {"ok": False,
                 "error": "give either ip (network printer) or printer_name (USB)"},
            )
            return

        try:
            data = base64.b64decode(data_b64, validate=True)
        except Exception as err:
            self._reply(400, {"ok": False, "error": "bad base64: %s" % err})
            return

        # USB / locally attached printer.
        if printer_name:
            try:
                send_to_local_printer(printer_name, data)
            except ValueError as err:
                self._reply(400, {"ok": False, "error": str(err)})
                return
            except OSError as err:
                LOG.warning("print to local printer %r failed — %s", printer_name, err)
                self._reply(
                    502,
                    {"ok": False,
                     "error": "local printer failed: %s" % err,
                     "printer_name": printer_name},
                )
                return
            LOG.info("printed %d bytes to local printer %r", len(data), printer_name)
            self._reply(200, {"ok": True, "bytes": len(data),
                              "printer_name": printer_name})
            return

        # Network printer.
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
    local = list_local_printers()
    if local.get("available"):
        LOG.info("local printers visible: %s",
                 ", ".join(local.get("printers") or []) or "(none)")
        if local.get("default"):
            LOG.info("system default printer: %s", local["default"])
    else:
        LOG.info("local printer listing unavailable: %s",
                 local.get("error", "unknown"))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        LOG.info("shutting down")
        server.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
