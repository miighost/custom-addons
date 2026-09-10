# Staff Allowance — Odoo 19 Community

Daily per-category allowances for **employees and contacts**, enforced
server-side, with plans, over-limit handling and plain-JSON endpoints.

---

## 1. No cron, no counter

The quota is never stored as a number that has to be reset. It is derived from
the day's order rows:

```
remaining = limit − units consumed on the beneficiary's local day
```

Tomorrow the date query returns nothing, so the quota resets by itself. Nothing
to schedule, nothing to fail overnight, and the full history stays queryable.

---

## 2. Who can hold an allowance

Both employees and contacts. Every allowance line, order and blocked attempt
inherits `staff.allowance.beneficiary.mixin`, which carries `employee_id` /
`partner_id` and enforces that exactly one is set. Categories declare who they
serve via **Applies To**: *Employees only*, *Contacts only*, or both.

Use the contact side for loyalty tiers, corporate accounts with a daily cap, or
partner staff who order through the same app.

---

## 3. The cascade — where a limit comes from

Most specific wins:

| # | Source | Where you set it |
|---|---|---|
| 1 | **Personal line** | Allowance tab on the employee or contact |
| 2 | **Plan line** | Allowances → Configuration → Plans |
| 3 | **Category default** | Allowances → Configuration → Categories |
| 4 | **Blocked** | category *Assigned Only*, or an exhaustive plan |

`_limit_for()` returns the limit **and its origin**, so the API tells the app
whether a number came from a personal line, a plan, or the category default.

### Plans (the tier)

A plan is a named set of category limits — *Staff*: Coffee 10 / Snacks 5;
*Manager*: Coffee 15 / Snacks 10. Assign it once on the person instead of
editing every category by hand. Tick **Plan Is Exhaustive** and the plan becomes
the complete list: anything not in it is blocked for those people.

**Copy Plan Limits** on the person materialises the plan as personal lines when
you need to tune one individual without leaving the tier.

---

## 4. What happens when they hit the limit

Set per category, under **When the Limit Is Reached**:

| Policy | Behaviour |
|---|---|
| **Block the order** (default) | Nothing is recorded. The API returns `429` with a clear message. The attempt is logged under Blocked Attempts. |
| **Allow, but require approval** | The order is created as **To Approve** and flagged over limit. A manager approves or refuses it. |
| **Allow and flag as over limit** | The order goes through, flagged for reporting. |

**Max Over Limit** caps how far past the limit the last two policies will go.
Beyond that it blocks regardless.

The message the staff member sees:

> Daily Coffee limit reached: 10 of 10 units used today. It resets tomorrow.

---

## 5. Daily usage is stored, not recomputed

`staff.allowance.usage` holds one row per **beneficiary / category / day**:
used, limit, remaining, over-by, order count, status, and which level of the
cascade the limit came from.

It is refreshed whenever an order is created, edited or deleted, and whenever
an allowance line changes. That matters for two reasons:

- **It is searchable.** A live computed figure cannot appear in a domain, a
  filter or a group-by. An earlier version tried to work around that with an
  in-memory search method, and Odoo 19 rejected the search view outright at
  install time. Stored columns make the monitoring views ordinary indexed
  queries.
- **It is history.** A row for a past day keeps the limit as it stood that day,
  so raising someone's limit today does not silently rewrite last week.

Quota *enforcement* still reads the order rows directly, so the usage table is
a reporting projection and can never let a bad number through. If it ever
drifts, `env['staff.allowance.usage'].action_rebuild_today()` rebuilds it.

## 6. Seeing who is over

| Where | Shows |
|---|---|
| **Allowance tab** (employee / contact) | Live per-category row: limit, used today, remaining, over by, and a colour-coded status — Available / Almost Used Up / Limit Reached / Over Limit / Blocked |
| **Monitoring → Daily Usage** | The stored table: used / limit / remaining / over-by per person, per category, per day — with pivot and graph |
| **Monitoring → At or Over Limit** | Everyone who has used up their allowance today |
| **Monitoring → Over-Limit Orders** | Orders recorded past the limit, grouped by person |
| **Monitoring → Blocked Attempts** | Every refused order, with the exact message returned to the app, the limit, and how much was already used |
| **Operations → To Approve** | The approval queue |
| **Orders → pivot / graph** | Consumption by person, category and day |

Blocked Attempts is the one that answers "who ran out of coffee at 11am and
should probably have a higher limit?" — a refused order leaves no order row, so
without this log it would be invisible.

---

## 7. Enforcement

- `_place_order()` on the category is the single decision point. The REST API,
  the backend and any future POS hook all call it, so they cannot drift apart.
- `_evaluate()` is the one function that computes limit / used / remaining /
  over-limit. The constraint, the UI status badge and the API all read from it.
- `create()` takes `SELECT … FOR UPDATE` on the beneficiary row before the
  constraint runs, so two simultaneous taps cannot both slip through.
- A savepoint wraps the insert: if a concurrent request wins the race, the
  refusal is logged as an attempt instead of blowing up the request.
- `@api.constrains` remains the final net for direct writes, imports and other
  modules.

**Day boundary:** the beneficiary's own timezone (`tz` on the employee or the
contact), falling back to the API user, then UTC. `order_date` is stamped at
creation, so a 23:58 order stays on its own day.

---

## 8. REST API

`type='http'`, flat JSON, no JSON-RPC envelope.

### `GET /api/allowance/categories`

```json
{
  "success": true,
  "beneficiary": { "type": "employee", "id": 7, "name": "Amina" },
  "categories": [{
    "code": "coffee", "name": "Coffee", "allowed": true,
    "limit": 10, "used": 3, "remaining": 7, "origin": "plan",
    "over_limit": false, "overdraft": 0, "count_mode": "qty",
    "day": "2026-09-10", "resets_at": "2026-09-10 21:00:00",
    "overdraft_policy": "block", "products": []
  }]
}
```

### `GET /api/allowance/quota?code=coffee`

One category, same shape.

### `POST /api/allowance/order`

```json
{ "code": "coffee", "product_id": 5, "qty": 1 }
```

Accepted → `200`:

```json
{ "success": true, "requires_approval": false,
  "order": { "id": 42, "reference": "ALW/2026/00042", "qty": 1,
             "state": "done", "is_over_limit": false, "over_by": 0 },
  "quota": { "limit": 10, "used": 4, "remaining": 6, "over_limit": false } }
```

Refused → `429` (quota) or `400` (bad request), always with the live quota
attached so the app can correct its display in the same round trip:

```json
{ "success": false, "error": "limit_reached",
  "message": "Daily Coffee limit reached: 10 of 10 units used today. It resets tomorrow.",
  "quota": { "limit": 10, "used": 10, "remaining": 0 } }
```

Error codes: `no_beneficiary`, `missing_code`, `unknown_category`, `bad_qty`,
`product_not_allowed`, `not_allowed`, `limit_reached`, `overdraft_exceeded`,
`forbidden`, `server_error`.

### `POST /api/allowance/cancel` → `{ "order_id": 42 }`

### `GET /api/allowance/history?date_from=&date_to=&code=&limit=`

### Plugging in your own API model

Routes are `auth="user"`. Resolve your token in `_beneficiary()` in
`controllers/main.py`, call `request.update_env(user=uid)`, and switch the
routes to `auth="public"`. Everything downstream is untouched — the controller
only translates HTTP into `_place_order()`.

---

## 9. FlutterFlow notes

1. Call `/api/allowance/categories` on page load; store the list in page state.
2. Show `used` / `limit`; disable the button when `remaining == 0` **and**
   `overdraft_policy == "block"`.
3. After every order, overwrite local state from `quota` in the response —
   never increment locally.
4. Branch on `error`, not the status code: `limit_reached` → show `message`,
   `overdraft_exceeded` → same, `product_not_allowed` → refresh the product list.
5. If `requires_approval` is true, show the order as pending, not confirmed.
6. Use `resets_at` (UTC) for a "resets in 4h 12m" countdown.

---

## 10. Model map

| Model | Role |
|---|---|
| `staff.allowance.category` | Coffee, Snacks… default limit, policy, **all the decision logic** |
| `staff.allowance.plan` / `.plan.line` | Reusable tiers |
| `staff.allowance.line` | Personal override + live status |
| `staff.allowance.order` | One consumption event; approval flow; over-limit flag |
| `staff.allowance.usage` | Stored daily totals — the reporting projection |
| `staff.allowance.attempt` | Refused orders, for reporting |
| `staff.allowance.beneficiary.mixin` | Employee-or-contact + timezone helpers |

## 11. Install

Copy `staff_allowance` into your addons path → restart → **Apps → Update Apps
List** → install **Staff Allowance**. Depends on `hr`, `product`, `mail`, all
Community. Ships with Coffee (10/day, blocks) and Snacks (5/day, approval with
2 extra), plus Staff and Manager plans.

---

## 12. Checking views before you install

`tools/check_views.py` statically validates every view against the models:
that each `<field>` exists on the right model (recursing into embedded
one2many subviews), that nothing in a `domain` is a non-stored field without a
`search` method, and that nothing grouped by is unstored.

```bash
cd staff_allowance && python3 tools/check_views.py
```

That last rule is the one that caused the original install failure — worth
running in CI before pushing to the server.
