# -*- coding: utf-8 -*-
"""Network sweep helpers — plain sockets, no Odoo imports.

Kept free of Odoo so it can be unit-tested standalone.
"""

import ipaddress
import socket
from concurrent.futures import ThreadPoolExecutor

# Ports worth asking about, and what an open one implies.
PORT_RAW = 9100      # raw ESC/POS ("JetDirect"): what generic thermal units use
PORT_HTTP = 80       # Epson ePOS printers expose an HTTP service here
PORT_HTTPS = 443
PORT_IPP = 631       # CUPS / IPP
PORT_LPD = 515       # line printer daemon

SCAN_PORTS = (PORT_RAW, PORT_HTTP, PORT_IPP, PORT_LPD)

MAX_HOSTS = 1024     # refuse anything wider than this
MAX_WORKERS = 128

# Real-time status request. Non-printing: the printer answers with one status
# byte and no paper moves. Safe to fire at unknown devices.
DLE_EOT_STATUS = b"\x10\x04\x01"


def parse_targets(spec, max_hosts=MAX_HOSTS):
    """Expand a scan spec into a list of address strings.

    Accepts, comma-separated:
        192.168.1.0/24
        192.168.1.10-192.168.1.60
        192.168.1.50
    """
    out = []
    seen = set()

    def add(addr):
        text = str(addr)
        if text not in seen:
            seen.add(text)
            out.append(text)

    for chunk in (spec or "").replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue

        if "-" in chunk:
            lo_s, hi_s = [p.strip() for p in chunk.split("-", 1)]
            lo = ipaddress.ip_address(lo_s)
            # Allow the shorthand 192.168.1.10-60
            if "." not in hi_s:
                prefix = lo_s.rsplit(".", 1)[0]
                hi_s = "%s.%s" % (prefix, hi_s)
            hi = ipaddress.ip_address(hi_s)
            if int(hi) < int(lo):
                lo, hi = hi, lo
            if int(hi) - int(lo) + 1 > max_hosts:
                raise ValueError(
                    "range %s covers more than %d addresses" % (chunk, max_hosts)
                )
            for value in range(int(lo), int(hi) + 1):
                add(ipaddress.ip_address(value))

        elif "/" in chunk:
            net = ipaddress.ip_network(chunk, strict=False)
            hosts = list(net.hosts()) or [net.network_address]
            if len(hosts) > max_hosts:
                raise ValueError(
                    "%s covers %d addresses, more than the %d limit"
                    % (chunk, len(hosts), max_hosts)
                )
            for host in hosts:
                add(host)

        else:
            add(ipaddress.ip_address(chunk))

        if len(out) > max_hosts:
            raise ValueError("scan covers more than %d addresses" % max_hosts)

    return out


def local_subnet_guess():
    """Best guess at the subnet the server sits on, as a /24."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # No packet is actually sent; this just picks the outbound interface.
        sock.connect(("8.8.8.8", 53))
        ip = sock.getsockname()[0]
    except OSError:
        ip = "192.168.1.1"
    finally:
        sock.close()
    return "%s.0/24" % ip.rsplit(".", 1)[0]


def check_port(host, port, timeout=0.4):
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
    except OSError:
        return False
    try:
        sock.close()
    except OSError:
        pass
    return True


def probe_escpos(host, port=PORT_RAW, timeout=0.8):
    """Ask a raw-port device for its status. Returns (responded, status_byte)."""
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
    except OSError:
        return False, None
    try:
        sock.settimeout(timeout)
        sock.sendall(DLE_EOT_STATUS)
        data = sock.recv(1)
        return (True, data[0]) if data else (False, None)
    except OSError:
        return False, None
    finally:
        try:
            sock.close()
        except OSError:
            pass


def http_banner(host, port=PORT_HTTP, timeout=0.8):
    """Grab a short HTTP response so Epson/ePOS units identify themselves."""
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
    except OSError:
        return ""
    try:
        sock.settimeout(timeout)
        sock.sendall(
            b"GET / HTTP/1.0\r\nHost: %s\r\nUser-Agent: odoo-printer-scan\r\n\r\n"
            % host.encode("ascii", "ignore")
        )
        chunks, total = [], 0
        while total < 2048:
            part = sock.recv(1024)
            if not part:
                break
            chunks.append(part)
            total += len(part)
        return b"".join(chunks).decode("latin-1", "replace")
    except OSError:
        return ""
    finally:
        try:
            sock.close()
        except OSError:
            pass


def classify(open_ports, escpos_ok, banner):
    """Turn raw findings into a device kind and a confidence."""
    low = (banner or "").lower()
    is_epson = "epson" in low or "epos" in low
    is_printer_http = is_epson or "printer" in low

    if PORT_RAW in open_ports and escpos_ok:
        return "escpos", "high"
    if PORT_RAW in open_ports and is_printer_http:
        return "escpos", "high"
    if PORT_RAW in open_ports:
        # Port 9100 is used by almost nothing else, but the device did not
        # answer a status query — some clones simply do not.
        return "escpos", "medium"
    if is_epson and (PORT_HTTP in open_ports or PORT_HTTPS in open_ports):
        return "epos", "high"
    if PORT_IPP in open_ports or PORT_LPD in open_ports:
        return "other", "medium"
    return "unknown", "low"


def scan_host(host, ports=SCAN_PORTS, timeout=0.4):
    """Probe one address. Returns a dict, or None when nothing answered."""
    open_ports = [p for p in ports if check_port(host, p, timeout=timeout)]
    if not open_ports:
        return None

    escpos_ok, status_byte = (False, None)
    if PORT_RAW in open_ports:
        escpos_ok, status_byte = probe_escpos(host, PORT_RAW, timeout=timeout * 2)

    banner = ""
    if PORT_HTTP in open_ports:
        banner = http_banner(host, PORT_HTTP, timeout=timeout * 2)

    kind, confidence = classify(open_ports, escpos_ok, banner)

    name = ""
    for marker in ("<title>", "Server:"):
        idx = banner.find(marker)
        if idx >= 0:
            tail = banner[idx + len(marker):]
            end = min(
                [i for i in (tail.find("<"), tail.find("\r"), tail.find("\n"), 80)
                 if i and i > 0] or [80]
            )
            name = tail[:end].strip()
            if name:
                break

    return {
        "host": host,
        "open_ports": open_ports,
        "kind": kind,
        "confidence": confidence,
        "escpos_verified": escpos_ok,
        "status_byte": status_byte,
        "banner_name": name[:120],
    }


def sweep(targets, ports=SCAN_PORTS, timeout=0.4, max_workers=MAX_WORKERS):
    """Scan many addresses concurrently. Returns findings in address order."""
    findings = []
    workers = max(1, min(max_workers, len(targets)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for result in pool.map(
            lambda h: scan_host(h, ports=ports, timeout=timeout), targets
        ):
            if result:
                findings.append(result)
    findings.sort(key=lambda r: tuple(int(p) for p in r["host"].split(".")))
    return findings
