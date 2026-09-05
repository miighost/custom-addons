# Network printing setup

Odoo 19 Community. Generic ESC/POS printers on the LAN (port 9100).

## How it works

One renderer (`models/escpos.py`), two transports. Which one a printer uses is a
single field on its record, so moving Odoo to the cloud later is a config
change, not a rewrite.

```
                          transport = server_socket        (Odoo on the shop LAN)
  POS browser --RPC--> Odoo server --TCP 9100--> printer

                          transport = browser_agent        (Odoo on a VPS / odoo.sh)
  POS browser --RPC--> Odoo server  (renders bytes only)
  POS browser --HTTP--> local agent on the till --TCP 9100--> printer
```

## 1. Confirm each printer actually speaks raw ESC/POS

From the machine running Odoo, for every printer IP:

```bash
# port open?
nc -zv 192.168.1.50 9100

# does it print? (should eject a line and cut)
printf '\x1b@ESC/POS OK\n\n\n\n\x1dV\x42\x00' | nc 192.168.1.50 9100
```

If paper comes out, you are done — no agent needed today.
If the port is closed but port 80 answers, the printer may speak ePOS instead,
which Odoo supports natively via `pos_epson_printer_restaurant`.

## 2. Install

```bash
./odoo-bin -u ss_print_pos_kitchen_receipt -d YOUR_DB
```

New in this version: `security/ir.model.access.csv`, `views/pos_config_views.xml`.
If the upgrade fails on `point_of_sale.pos_config_view_form` not existing, drop
`views/pos_config_views.xml` from `__manifest__.py` — nothing else depends on it.

## 3. Configure printers

**Point of Sale → Configuration → Network Printers**

| Field | Value |
|---|---|
| Name | Kitchen |
| IP address | 192.168.1.50 |
| Port | 9100 |
| Transport | Odoo server opens the socket |
| Paper width | 80 mm (48 characters) |
| POS categories | the food categories |

Repeat for Bar with the drink categories. **Leave POS categories empty and the
printer receives every line** — that is the single-printer setup.

Two buttons on the form:

- **Probe port** — opens and closes a TCP connection. Confirms reachability
  without wasting paper.
- **Test print** — renders and sends a real sample ticket.

Then enable auto-print per POS in **Point of Sale → Configuration → Point of
Sale → your POS → Kitchen Receipt Printing**.

## 4. When you move Odoo to the cloud

The server can no longer reach `192.168.x.x`. Switch each printer to
**Transport = Local agent on the till** and run the agent on the till machine:

```bash
python3 agent/pos_print_agent.py
```

Stdlib only, no pip install. It binds to `127.0.0.1:8765` and refuses to
connect to anything outside a private address range.

Tighten it for production:

```bash
python3 agent/pos_print_agent.py \
  --allow 192.168.1.50 --allow 192.168.1.51 \
  --origin https://yourcompany.odoo.com
```

Keep it running with `launchd` (macOS), a systemd unit (Linux), or Task
Scheduler (Windows).

### Two browser caveats for that phase

1. **Mixed content.** `http://127.0.0.1` is a *potentially trustworthy* origin,
   so an https Odoo page is allowed to call it. Calling a printer or agent at
   `http://192.168.x.x` from an https page is blocked — keep the agent on
   loopback.
2. **Local Network Access.** Chrome 142 added a permission prompt for pages
   that reach loopback or private addresses. The cashier grants it once per
   site. The agent already sends `Access-Control-Allow-Private-Network: true`.

## Debugging

Everything logs to the browser console under `[ss_kot]`. Open the POS, press
F12, and fire an order. You will see the printer list, the dispatch per
station, and the exact error if one fails. Server-side socket errors also land
in the Odoo log and are shown to the cashier as a sticky notification.

## What changed from the original module

- `pos.printer.print()` calls removed. That is the *receipt* printer service —
  one default device — so it could never address two stations, and with no
  ePOS/IoT printer configured it silently fell back to `window.print()`.
- Every `catch (_e) {}` replaced with real logging. Silent failure was the
  reason nothing appeared to happen.
- Category routing now uses real POS categories on the printer record instead
  of matching product names against a keyword list. The old heuristic sent
  "Water Melon Salad" to the bar; it is kept as a deprecated fallback.
- `views/views.xml` was an empty `<odoo><data/></odoo>`, so `kitchen_print` and
  `kitchen_print_auto` existed in the database but had no interface — which is
  why automatic printing never fired.
- The print counter no longer advances when nothing reached a printer, so a
  failed first attempt is not labelled "2nd Print (Re-Order)".
- Originals kept in `_backup/`.

## Still worth doing

KOT state (`printed_qty`, `was_kot_printed`, `kot_print_count`) lives only on
in-memory JS objects. Refresh the browser or switch till and every ticket
reprints as "1st Print (Original)". Persisting it on the order — or reading
Odoo's native `last_order_preparation_change` — is the next fix.

The duplicate asset tree under `models/static/` is dead code; the manifest
loads from `static/`. Safe to delete.
