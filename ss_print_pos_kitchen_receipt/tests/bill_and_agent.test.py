"""Bill renderer + agent USB path. Run: python3 tests/bill_and_agent.test.py"""
import base64, importlib.util, json, os, re, socket, sys, threading, time
import urllib.request, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

esc = load("escpos", "models/escpos.py")
agent = load("agent", "agent/pos_print_agent.py")

def decode(raw):
    out, i = bytearray(), 0
    while i < len(raw):
        b = raw[i]
        if b == 0x1b:
            n = raw[i+1:i+2]
            i += 2 if n in (b"@",) else (3 if n in (b"a", b"E", b"-", b"d") else 2)
        elif b == 0x1d:
            n = raw[i+1:i+2]
            i += 3 if n == b"!" else (4 if n == b"V" else 2)
        else:
            out.append(b); i += 1
    return bytes(out).decode("cp437", "replace")

passed = 0
def ok(label):
    global passed
    passed += 1
    print("  ok  %s" % label)

print("money formatting")
assert esc.format_amount(1234.5, {"symbol": "$", "position": "before"}) == "$1,234.50"
ok("symbol before")
assert esc.format_amount(1234.5, {"symbol": "SOS", "position": "after"}) == "1,234.50 SOS"
ok("symbol after")
assert esc.format_amount(7, {"symbol": "", "decimals": 0}) == "7"
ok("zero-decimal currency")
assert esc.format_amount(None, {}) == "0.00"
ok("None is not a crash")
assert esc.format_amount("nonsense", {}) == "0.00"
ok("garbage is not a crash")

print("bill rendering")
bill = {
    "company_name": "Liban Restaurant",
    "company_details": ["Maka Al Mukarama Rd", "Mogadishu", "+252 61 000 0000"],
    "vat": "VAT: SO123456",
    "order_ref": "Order 00042",
    "datetime": "2026-09-05 19:41:00",
    "cashier": "Abdishakur",
    "table_name": "12",
    "lines": [
        {"name": "Chicken Suqaar with Rice", "qty": 2, "price_unit": 12.5,
         "discount": 0, "subtotal": 25.0},
        {"name": "Fanta 300ml", "qty": 3, "price_unit": 1.5,
         "discount": 10, "subtotal": 4.05},
    ],
    "subtotal": 29.05,
    "taxes": [{"name": "Tax", "amount": 1.45}],
    "total": 30.50,
    "payments": [{"name": "Cash", "amount": 40.0}],
    "change": 9.50,
    "footer_note": "Thank you\nMahadsanid",
    "tracking_number": "042",
    "currency": {"symbol": "$", "position": "before", "decimals": 2},
}
raw = esc.render_bill(bill, width=48)
text = decode(raw)
print("\n".join("      | " + l for l in text.split("\n")))

assert raw.startswith(b"\x1b@"), "must initialise the printer"
ok("starts with ESC @")
assert b"\x1dVB\x00" in raw, "must cut"
ok("ends with a cut")
for needle in ("Liban Restaurant", "Order 00042", "Chicken Suqaar",
               "TOTAL", "$30.50", "Cash", "$40.00", "Mahadsanid", "042"):
    assert needle in text, "missing %r" % needle
ok("carries shop, order, items, total, payment, change, footer, tracking")
over = [l for l in text.split("\n") if len(l) > 48]
assert not over, "overflowing lines: %r" % over
ok("no line exceeds 48 columns")

narrow = decode(esc.render_bill(bill, width=32))
over = [l for l in narrow.split("\n") if len(l) > 32]
assert not over, "58mm overflow: %r" % over
ok("58mm paper also fits")

assert "10%" in text
ok("discount is shown")

print("empty / minimal bill does not crash")
tiny = decode(esc.render_bill({"total": 0}, width=48))
assert "TOTAL" in tiny
ok("minimal dict renders")
assert decode(esc.render_bill(None, width=48))
ok("None renders")

print("agent: USB path")
calls = []
def fake_local(printer_name, payload, job_name="Odoo POS"):
    calls.append((printer_name, payload))
agent.send_to_local_printer = fake_local

PORT = 18799
threading.Thread(
    target=agent.main, args=(["--host", "127.0.0.1", "--port", str(PORT)],), daemon=True
).start()
time.sleep(1)

def post(body):
    req = urllib.request.Request(
        "http://127.0.0.1:%d/print" % PORT,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    return urllib.request.urlopen(req, timeout=5)

payload_b64 = base64.b64encode(raw).decode()
res = json.loads(post({"printer_name": "XP-58", "payload_b64": payload_b64}).read())
assert res["ok"] and res["printer_name"] == "XP-58", res
ok("agent accepts a USB job")
assert calls and calls[0][0] == "XP-58" and calls[0][1] == raw
ok("bytes reach the USB backend unaltered")

with urllib.request.urlopen("http://127.0.0.1:%d/printers" % PORT, timeout=5) as r:
    listing = json.loads(r.read())
assert "printers" in listing
ok("/printers responds (available=%s)" % listing.get("available"))

for bad, expect in (
    ({"payload_b64": payload_b64}, 400),
    ({"printer_name": "X"}, 400),
):
    try:
        post(bad); raise AssertionError("expected HTTP %d" % expect)
    except urllib.error.HTTPError as e:
        assert e.code == expect, "%s -> %s" % (bad, e.code)
ok("missing target or payload is rejected with 400")

def boom(*a, **k):
    raise OSError("The printer is offline")
agent.send_to_local_printer = boom
try:
    post({"printer_name": "XP-58", "payload_b64": payload_b64})
    raise AssertionError("expected 502")
except urllib.error.HTTPError as e:
    body = json.loads(e.read())
    assert e.code == 502 and "offline" in body["error"], body
ok("a failing USB printer returns 502 with the real reason")

print("\n%d/%d checks passed" % (passed, passed))
