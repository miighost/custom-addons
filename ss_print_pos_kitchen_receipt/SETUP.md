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

This Odoo runs on Windows, and the module is loaded from

    C:\Program Files\Odoo 19.0.20260228\server\addons\ss_print_pos_kitchen_receipt

so copy the folder there before upgrading — editing the Mac copy alone changes
nothing. Then upgrade from **Apps → Odoo Print POS Kitchen Receipt → Upgrade**,
or restart the service with:

```
"C:\Program Files\Odoo 19.0.20260228\python\python.exe" ^
  "C:\Program Files\Odoo 19.0.20260228\server\odoo-bin" ^
  -c "C:\Program Files\Odoo 19.0.20260228\server\odoo.conf" ^
  -u ss_print_pos_kitchen_receipt -d YOUR_DB --stop-after-init
```

New in this version: `security/ir.model.access.csv`,
`views/pos_config_views.xml`, `wizards/scan_printers_views.xml`.

Every external reference the module makes has been checked against the Odoo
19.0 source:

| Reference | Used for |
|---|---|
| `point_of_sale.menu_point_config_product` | the Configuration menu both menu items hang off |
| `point_of_sale.group_pos_user` | read access to printers, for cashiers |
| `point_of_sale.group_pos_manager` | full access to printers and the scan wizard |

Odoo 19 breaking changes this module had to account for:

- `<group>` inside a **search** view no longer accepts `expand`, `string` or
  `name="group_by"`. Use a bare `<group>`.
- `point_of_sale.menu_point_config` does not exist. The POS Configuration menu
  is `point_of_sale.menu_point_config_product`.

The module also deliberately inherits **no** server-side view. The kitchen
printing toggles get their own standalone list under
**Configuration -> Kitchen Printing** rather than being xpath'd into
`pos_config_view_form`, because that form's internal structure (`sheet`,
`notebook`, `setting`) shifts between versions and an xpath that misses stops
the whole module from installing. Every view this module ships owns its markup
end to end.

## 3. Find the printers automatically

**Point of Sale → Configuration → Scan for Printers**

The subnet is pre-filled from the Odoo server's own address (yours will come out
as `192.168.13.0/24`). Also accepts `192.168.13.10-60`, a single address, or a
comma-separated mix. Capped at 1024 addresses per scan.

The sweep is concurrent — a full /24 across four ports finishes in about three
seconds even when every address times out.

| Result | Meaning |
|---|---|
| Raw ESC/POS · High · answered status query | A real thermal printer. Port 9100 open and it replied to a non-printing `DLE EOT` status request. |
| Raw ESC/POS · Medium | Port 9100 open but the device ignored the status query. Many clones do. Test it. |
| Epson ePOS · High | Identifies as Epson over HTTP. Odoo supports these natively via `pos_epson_printer_restaurant`. |
| Other printer service | IPP (631) or LPD (515) only — not usable for raw ticket printing. |

Addresses already registered show in orange and cannot be added twice.

**Test print** on any row sends a real sample ticket to that address
immediately, before you commit to a record. That is how you work out which
physical printer sits at which IP: fire it, see which station spits paper, name
the row, tick **Add**, then **Add selected**.

The status query is safe to fire at unknown devices — it is a real-time
request that moves no paper.

## 4. Configure printers

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

### How routing decides

- Categories are matched **including subcategories**. Assigning `Drinks` to the
  bar also routes `Drinks / Hot` and `Drinks / Cocktails`, so you set the parent
  once instead of maintaining a list.
- A printer with **no** categories is a catch-all and takes every line.
- A line whose product matches **no** printer raises a sticky warning naming the
  product, because that dish would otherwise never be cooked and nothing on
  screen would say so. Fix it by adding the category to a printer, or by leaving
  one printer's categories empty as a backstop.

The safest configuration for a two-station kitchen is to give the Bar its drink
categories and leave the **Kitchen catch-all** (no categories). Anything you add
to the menu later then reaches the kitchen by default instead of vanishing.

Two buttons on the form:

- **Probe port** — opens and closes a TCP connection. Confirms reachability
  without wasting paper.
- **Test print** — renders and sends a real sample ticket.

### When the ticket prints

**Point of Sale → Configuration → Kitchen Printing**, one row per POS:

| Setting | Effect |
|---|---|
| Show Print KOT button | Off hides the manual reprint button so staff cannot send duplicate tickets. The green Order button is unaffected. |
| Automatic printing | Master switch for printing without a button press. |
| Print automatically | `When the order is sent` (table service) or `At payment` (counter service). |

Three triggers exist:

| Trigger | Fires | Prints |
|---|---|---|
| Green **Order** button | On click | Only what changed |
| **Print KOT** button | On click | Everything |
| Automatic, `on_send` | Leaving the order screen — to the floor plan, payment, or the order list | Only what changed |
| Automatic, `on_payment` | Receipt screen opens, i.e. after payment | Only what changed |

`on_send` treats *leaving the order screen* as the send-to-kitchen moment,
which is what a waiter physically does when they finish taking an order. The
two automatic triggers are mutually exclusive — the ticket cannot print twice
for the same change — and an in-flight guard means walking in and out of the
screen quickly cannot fire two tickets either.

Automatic printing never fires on an empty order, or when nothing has changed
since the kitchen last saw it.

### Monitoring

The printer list carries a live **Status** badge (Online / Unreachable / Not
checked) plus **Last ticket sent** and **Last error**, and per-row Probe and
Test buttons. Status is written on a separate database cursor, so it survives
the rollback a failed print causes — the record still shows *why* it failed
after the error dialog closes. Select several printers and hit **Probe** to
refresh them all; filter by **Online** / **Unreachable** to spot a station that
dropped off mid-service.

## 5. Your setup: 2 bars, 1 kitchen, 1 USB bill printer

### The printer records

| Name | Role | Connection | Transport | POS categories |
|---|---|---|---|---|
| Kitchen | Kitchen / bar ticket | Network `192.168.13.x:9100` | Odoo server socket | **leave empty** |
| Bar 1 | Kitchen / bar ticket | Network `192.168.13.x:9100` | Odoo server socket | soft drinks, juices, water |
| Bar 2 | Kitchen / bar ticket | Network `192.168.13.x:9100` | Odoo server socket | cocktails, beer, spirits |
| Bill | Customer bill | Local printer on the till | Local agent | (ignored) |

**Leave the Kitchen's categories empty on purpose.** Empty means catch-all: it
takes every line, including any product you add to the menu later and forget to
categorise. The bars take their named categories; the kitchen takes the rest.
The alternative — naming the kitchen's categories explicitly — means a new dish
in a new category prints nowhere and is never cooked.

An order with food, a soft drink and a cocktail produces three tickets: the
kitchen gets all three lines, Bar 1 only the soft drink, Bar 2 only the
cocktail.

### The USB bill printer

It is plugged into the till, so the Odoo server cannot see it. It is driven by
the agent:

```
python3 agent/pos_print_agent.py
```

**No installation required.** The agent is standard library only. On Windows it
uses pywin32 if it happens to be present, and otherwise prints through the
printer's Windows **share** with `copy /b`, which needs nothing installed and
no internet.

To use the share path:

1. Settings → Printers & scanners → your bill printer → Printer properties →
   Sharing → **Share this printer**, share name `POSBILL` (no spaces).
2. Put `POSBILL` in Odoo's **Local printer name** field.

Either way the bytes reach the printer raw, so the cut and cash-drawer commands
survive rather than being re-rendered by the driver. On macOS and Linux the same
is done with `lp -o raw`.

With the agent running, <http://127.0.0.1:8765/printers> lists every printer the
till can see, with share names where they exist and which backend is in use.
Type one of those names into Odoo verbatim.

If you later get internet and want the pywin32 path (marginally faster, no share
needed), install it into the Python that runs the agent — for Odoo's bundled
Python that is:

```
"C:\Program Files\Odoo 19.0.20260228\python\python.exe" -m pip install pywin32
```

Offline, download the matching `.whl` on another machine and
`python.exe -m pip install <file>.whl`. The agent picks it up on next start; no
configuration changes.

The bill prints by itself when the receipt screen opens. **Print Bill** on that
screen is the retry if it does not.

### Health check at session start

The first time the order screen opens, every network printer is probed. If a
station is unreachable you get a sticky red warning naming it and its IP,
before the first order rather than at 8pm with a queue at the till. All good
gives a brief green confirmation.

### Pre-service checklist

1. Agent running on the till (needed for the bill only).
2. Open the POS — wait for the health-check notification. Green means all three
   network printers answered.
3. Ring up one item from each bar plus one food item, leave the order screen:
   three tickets, each with only its own lines.
4. Pay it: the bill prints on the USB printer.

If step 2 warns, fix that station before opening. If step 3 or 4 misbehaves,
F12 → Console → filter `ss_kot`.

## 6. When you move Odoo to the cloud

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
