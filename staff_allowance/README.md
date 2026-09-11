# Staff Allowance — Odoo 19 Community

Daily limits on **POS categories** for individual employees and contacts.
Free by default; capped only where you say so.

---

## 1. Nothing is restricted until you add a rule

A rule names **one person** and **one POS category**. That is the whole
model. Install the module and nobody is affected. Cap one employee's coffee
and every other employee, and every other category, is untouched.

- No rule for that person + that category → no limit at all
- A rule with limit 10 → 10 per day
- A rule with limit 0 → that category is blocked for that person
- Archive the rule → they are free again, and the setting is kept

## 2. Built on your real POS data

Categories are `pos.category` records — the ones your POS already uses. There
is no parallel category list to maintain. An order's category is taken from
the product's own POS category, so the app can just send a `product_id`.

## 3. The quota resets itself

```
remaining = limit − consumed on that person's local day
```

Tomorrow the date query returns nothing, so it resets on its own. No counter
to reset, no cron job to fail overnight, and the history stays queryable.
The day boundary is the beneficiary's own timezone; `order_date` is stamped
at creation, so a 23:58 order stays on its own day.

## 4. What happens at the limit

Set per rule:

| Policy | Behaviour |
|---|---|
| **Block the order** (default) | Refused. The API returns `429` with a clear message and the attempt is logged. |
| **Allow, but require approval** | Created as **To Approve**, flagged over limit. |
| **Allow and flag as over limit** | Goes through, flagged for reporting. |

**Tolerance** caps how far past the limit the last two will stretch.

The message the person sees:

> Daily Coffee limit reached: 10 of 10 items used today. It resets tomorrow.

## 5. Plans

A plan is a reusable set of rules — *Kitchen Staff*, *Managers* — assigned in
one click. A plan only covers the categories listed in it; anything else stays
free. A personal rule always wins over the plan. **Copy Plan Into Rules**
turns the plan into personal rules when you need to tune one individual.

## 6. Seeing who is over

| Where | Shows |
|---|---|
| **Allowance tab** (employee / contact) | Live per-rule row: limit, used, remaining, and a colour-coded status |
| **Monitoring → Daily Usage** | Stored table, one row per person / category / day, with pivot and graph |
| **Monitoring → At or Over Limit** | Everyone who has used their allowance up |
| **Monitoring → Over-Limit Orders** | Orders recorded past the limit |
| **Monitoring → Blocked Attempts** | Every refusal, with the exact message returned and the limit at the time |
| **Operations → To Approve** | The approval queue |

Blocked Attempts matters because a refused order leaves no order row — without
the log it would be invisible.

`staff.allowance.usage` is a stored projection, refreshed whenever an order or
a rule changes. Enforcement always reads the order rows directly, so the table
can never let a bad number through. `env["staff.allowance.usage"].action_rebuild()`
rebuilds it if it ever drifts.

## 7. Enforcement

- `staff.allowance.rule._place_order()` is the single decision point; the API,
  the backend and any POS hook all call it.
- `_evaluate()` is the only place limit / used / remaining / over-limit are
  computed. The constraint, the status badges and the API all read from it.
- `create()` takes `SELECT … FOR UPDATE` on the beneficiary row before the
  constraint runs, so two simultaneous taps cannot both slip through.
- A savepoint wraps the insert: if a concurrent request wins the race, the
  refusal is logged as an attempt instead of failing the request.
- `@api.constrains` is the final net for direct writes and imports.

## 8. REST API

`type='http'`, flat JSON, no JSON-RPC envelope.

### `GET /api/allowance/rules`

Only the categories this person is capped in. Everything else is free.

```json
{
  "success": true,
  "beneficiary": { "type": "employee", "id": 7, "name": "Amina" },
  "default_is_free": true,
  "rules": [{
    "category_id": 3, "category_name": "Coffee",
    "restricted": true, "origin": "personal",
    "limit": 10, "used": 3, "remaining": 7,
    "count_mode": "qty", "policy": "block",
    "over_limit": false, "overdraft": 0,
    "day": "2026-09-11", "resets_at": "2026-09-11 21:00:00"
  }]
}
```

### `GET /api/allowance/quota?product_id=12`

Also accepts `?category_id=3`. For an uncapped category:

```json
{ "success": true, "restricted": false, "origin": "free",
  "limit": null, "remaining": null, "used": 2 }
```

`limit` and `remaining` are **null**, not 0, when there is no rule — so an app
testing `remaining == 0` can never block a free user by mistake. Check
`restricted` first.

### `POST /api/allowance/order`

```json
{ "product_id": 12, "qty": 1 }
```

Accepted → `200` with the order and the refreshed `quota`.
Refused → `429` (quota) or `400` (bad request), always with `quota` attached
so the app can correct its display in the same round trip.

Error codes: `no_beneficiary`, `missing_category`, `bad_qty`, `limit_reached`,
`tolerance_exceeded`, `forbidden`, `server_error`.

### `POST /api/allowance/cancel` → `{ "order_id": 42 }`
### `GET /api/allowance/history?date_from=&date_to=&category_id=&limit=`

### Your own API model

Routes are `auth="user"`. Resolve your token in `_beneficiary()` in
`controllers/main.py`, call `request.update_env(user=uid)`, switch the routes
to `auth="public"`. Nothing downstream changes.

## 9. FlutterFlow notes

1. Call `/api/allowance/rules` on login. An empty list means the person is
   capped in nothing — show no counters at all.
2. For a product, check `restricted` first. If false, no badge, no blocking.
3. After each order, overwrite local state from `quota` in the response.
   Never increment locally.
4. Branch on `error`, not the status code.
5. If `requires_approval` is true, show the order as pending, not confirmed.

## 10. Model map

| Model | Fields | Role |
|---|---|---|
| `staff.allowance.rule` | 11 | One person + one POS category + a limit. All the logic. |
| `staff.allowance.plan` / `.plan.line` | 12 | Reusable tiers |
| `staff.allowance.order` | 15 | One consumption event; approval flow |
| `staff.allowance.usage` | 8 | Stored daily totals for reporting |
| `staff.allowance.attempt` | 10 | Refused orders |
| `staff.allowance.beneficiary.mixin` | 4 | Employee-or-contact + timezone helpers |

Dropped in this version: the whole custom `staff.allowance.category` model
(20 fields) plus `assigned_only`, `fallback`, `unlimited`, `allowed`,
`applies_to`, `product_ids`, `origin`, `strict`, `code`, `color`, `note` on
plans, and `user_id` / `company_id` where nothing used them.

## 11. Install

Copy into your addons path, restart the service, **Apps → Update Apps List**,
install **Staff Allowance**. Depends on `hr` and `point_of_sale`, both
Community.

**Restart the service on every upgrade.** Odoo re-reads XML on upgrade but
does not reload Python — model changes need a restart.

## 12. Known issue: search views

Custom search views on these models failed to install repeatedly, always with
a `ParseError` that hides the real message. This build ships **no custom
search views** — the lists use Odoo default search, which works fine.

`views/diagnostic_search_views.xml` (not loaded) settles it in one run. It has
eight minimal search views on `staff.allowance.order`, each adding exactly one
suspect construct. Records load in order and Odoo stops at the first invalid
one, so the record id in the error names the culprit.

1. Add `"views/diagnostic_search_views.xml",` to the `data` list
2. Restart, upgrade
3. Report which `diag_*` id fails, or that all eight pass

| id | construct |
|---|---|
| `diag_a_baseline` | plain stored Char only |
| `diag_b_string_attr` | `string=` label on a search field |
| `diag_c_many2one` | many2one search field |
| `diag_d_mixin_field` | field from the beneficiary mixin |
| `diag_e_mixin_domain` | filter domain on a mixin Selection |
| `diag_f_group_by` | group-by filter |
| `diag_g_group_wrapper` | `<group>` Group By wrapper |
| `diag_h_context_today` | date filter using `context_today()` |

Or get the real message directly:

```bash
./odoo-bin -d YOUR_DB -u staff_allowance --stop-after-init \
    --log-handler odoo.addons.base.models.ir_ui_view:DEBUG
```

## 13. Pre-flight check

```bash
cd staff_allowance && python3 tools/check_views.py
```

Validates every view against the models: fields exist (recursing into embedded
one2many subviews), no domain uses a non-stored field without a `search`
method, nothing groups by an unstored field, and every model with a search
view has a resolvable `_rec_name`.
