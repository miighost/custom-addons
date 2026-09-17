# Staff Allowance — Odoo 19 Community

Daily limits on **POS categories** for individual employees and contacts.
Free by default; capped only where you say so.

---

## 1. Nothing is restricted until you add a rule

A rule names **one contact** and **one POS category**. That is the whole
model. Install the module and nobody is affected. Cap one employee's coffee
and every other employee, and every other category, is untouched.

**Limits are set on the contact.** An employee is handled through their work
contact — the contact Odoo creates for every employee, links to their user,
and the one you pick as the customer in the POS. So a person has one set of
limits and one counter, whether they order at the POS or in the app.

### The flow

1. **Configuration → Plans** (optional): ready-made sets of limits, e.g.
   *Kitchen Staff: Drinks 3/day, Food 1/day*.
2. **People → Give an Allowance**: pick the person, choose a plan and/or add
   personal limits, Save. Staff are listed under their own name. Opening it
   for someone who already has limits shows theirs, so the same button
   changes or removes them.
3. **Sell in the POS** with that person as the customer. Nothing else to do.
4. **Today** shows who used what; **Reporting** has the analysis.

**Only people with a rule or a plan are tracked**, and only in the categories
those cover. Everyone else is not recorded at all — Orders and Today stay
about the people you actually limit.

| Where | What you do there |
|---|---|
| **Allowances → People** | Everyone with an allowance: plan, limits, today's status. **Give an Allowance** adds or changes one. |
| **Contacts → the person → Allowance tab** | The same plan and limits with today's usage; **Give an Allowance** / **Change Limits** opens the same window. |
| **Employees → the person → Allowance tab** | The same, for their contact; **Edit Limits** opens the window for them. |

Limits are always changed through **Give an Allowance**, from whichever of
these you start. That keeps one way to do it, and it works for HR officers,
who manage allowances but usually may not edit contacts.
| **Allowances → Configuration → Rules** | Every personal rule in one list, for managers. |

- No rule for that person + that category → no limit at all
- A rule with limit 10 → 10 per day
- A rule with limit 0 → that category is blocked for that person
- Archive the rule → they are free again, and the setting is kept

## 2. Where consumption comes from

Two sources, both feeding the same ledger:

| Source | How | Enforcement |
|---|---|---|
| **Odoo POS** | `pos.order` is hooked. Once a sale with a customer set is paid, each line is recorded against that customer's allowance. | At **Validate** the cashier is stopped (Block) or warned (the other policies). What is sold is always recorded — a sale that happened is a fact — and over-limit sales are flagged. |
| **FlutterFlow app** | The app calls `POST /api/allowance/order`. | Blocked or sent for approval per the rule. |

**A POS sale with no customer on the ticket charges nobody.** There is no
rule to apply without a partner, so the sale is ignored by the allowance
system entirely. If a staff member's coffee should count, their contact has
to be selected on the order.

Refund and zero-quantity lines do not consume an allowance. Changing the
customer or the lines on a ticket rewrites its allowance entries. An unpaid
or parked ticket counts nothing until it is paid, so one that gets cancelled
costs nothing. A paid ticket cannot be cancelled in Odoo, and refunding it
does not give the allowance back.

## 3. Built on your real POS data

Categories are `pos.category` records — the ones your POS already uses. There
is no parallel category list to maintain.

A sale counts against **every** POS category of the product that caps the
customer, parent categories included: a limit on *Drinks* also covers a
product in *Drinks / Coffee*. When no category caps the customer, nothing is
recorded. The app can just send a `product_id`.

## 4. The quota resets itself

```
remaining = limit − consumed on that person's local day
```

Tomorrow the date query returns nothing, so it resets on its own. No counter
to reset, no cron job to fail overnight, and the history stays queryable.
The day boundary is the beneficiary's own timezone, else their company's —
never that of whoever recorded the order. `order_date` is stamped at
creation, so a 23:58 order stays on its own day.

## 5. What happens at the limit

### In the POS

The rule's **At the Limit** setting decides what the cashier sees when they
validate a sale that goes over:

| At the Limit | In the POS |
|---|---|
| **Block the order** | "Allowance limit reached" — the sale cannot be validated. Take items off the ticket. The refusal is logged in **Blocked Attempts**. |
| **Allow, but require approval** / **Allow and flag** | A warning; **Sell anyway** completes the sale, recorded and flagged **Over Allowance**. |

With a **Tolerance**, the warning applies up to that many extra; past it, the
sale is blocked like Block.

Nothing is checked unless the ticket has a customer: for staff, pick their
contact (it has the employee's name). See section 13.

### In the app

Set per rule, and applies to app orders:

| Policy | Behaviour |
|---|---|
| **Block the order** (default) | Refused. The API returns `429` with a clear message and the attempt is logged. |
| **Allow, but require approval** | Created as **To Approve**, flagged over limit. |
| **Allow and flag as over limit** | Goes through, flagged for reporting. |

**Tolerance** caps how far past the limit the last two will stretch.

The message the person sees:

> Daily Coffee limit reached: 10 of 10 items used today. It resets tomorrow.

## 6. Plans

A plan is a reusable set of rules — *Kitchen Staff*, *Managers* — assigned in
one click. A plan only covers the categories listed in it; anything else stays
free. A personal rule always wins over the plan, and archiving a plan frees
everyone on it. **Copy Plan Into Rules**
turns the plan into personal rules when you need to tune one individual.

## 7. Seeing who is over

| Where | Shows |
|---|---|
| **Today** (where Allowances opens) | Everyone with a limit who used any today, grouped by person: one line per category with used, limit, remaining, the products taken ("Espresso ×2, Latte ×1") and a colour status. Click a line to see its order lines. |
| **People** | Everyone with a rule or plan, their limits in one line and today's status |
| **Orders → All Orders** | Every tracked sale, grouped by person |
| **Orders → To Approve** | The approval queue |
| **Reporting → Usage Analysis** | Pivot and graph of usage per person, category and day; last 30 days by default |
| **Reporting → Over-Limit Orders** | Sales recorded past a limit, grouped by person |
| **Reporting → Blocked Attempts** | Every refusal — at the POS or in the app — with the message shown |
| **Contact → Allowance tab** | One person's rules with today's usage (read-only copy on the employee) |
| **Point of Sale → Orders** | **Over Allowance** filter and column; an **Allowance** button on each recorded order |

Every list has **Today / Last 7 Days** filters, a date picker, a left panel by
category and status, and **Group By** Contact, POS Category, Day or Source.
The filters a menu opens with are only a starting point: remove them to see
everything, and save a favourite for views you use often.

An order's **Over** flag is decided when the sale happens, against what was
already used that day; later sales never change it.

Blocked Attempts matters because a refused order leaves no order row — without
the log it would be invisible.

Allowance orders are read-only in the backend (no **New** button): they come
from POS sales and the app.

`staff.allowance.usage` is a stored projection, refreshed whenever an order or
a rule changes. Enforcement always reads the order rows directly, so the table
can never let a bad number through. `env["staff.allowance.usage"].action_rebuild()`
rebuilds it if it ever drifts.

## 8. Enforcement

- `staff.allowance.rule._place_order()` is the single decision point; the API,
  the backend and any POS hook all call it.
- `_evaluate()` is the only place limit / used / remaining / over-limit are
  computed. The constraint, the status badges and the API all read from it.
- `create()` touches the beneficiary row, so two simultaneous orders for the
  same person conflict: Odoo retries the second request, which then sees the
  first order. A `SELECT … FOR UPDATE` is not enough here — under Odoo's
  REPEATABLE READ the waiting request still reads its old snapshot.
- A savepoint wraps the insert: if the constraint refuses it, the refusal is
  logged as an attempt instead of failing the request.
- `@api.constrains` is the final net for direct writes and imports. The only
  entries it lets past the limit are those linked to a paid POS sale for the
  same customer — decided from that sale, not from a context key a caller
  could set. Ordinary users cannot create allowance orders directly.
- `staff.allowance.usage` has a database unique index on person / category /
  day.

## 9. REST API

`type='http'`, flat JSON, no JSON-RPC envelope.

### `GET /api/allowance/rules`

Only the categories this person is capped in. Everything else is free.

```json
{
  "success": true,
  "beneficiary": { "id": 41, "name": "Amina" },
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

Accepted → `200` with the order and the refreshed `quota`. `order` is `null`
when no rule or plan covers the category: the order is allowed and not tracked.
Refused → `429` (quota) or `400` (bad request), always with `quota` attached
so the app can correct its display in the same round trip.

Error codes: `no_beneficiary`, `missing_category`, `bad_qty`, `bad_request`,
`limit_reached`, `tolerance_exceeded`, `forbidden`, `not_found`,
`not_cancellable`, `server_error`.

### `POST /api/allowance/cancel` → `{ "order_id": 42 }`

Withdraws an app order that is still **To Approve**. Anything else — a done
order, a POS sale — returns `409 not_cancellable`: cancelling an order that
was already consumed would hand the quota back.

### `GET /api/allowance/history?date_from=&date_to=&category_id=&limit=`

### Your own API model

Routes are `auth="user"`. Resolve your token in `_beneficiary()` in
`controllers/main.py`, call `request.update_env(user=uid)`, switch the routes
to `auth="public"`. Nothing downstream changes.

## 10. FlutterFlow notes

1. Call `/api/allowance/rules` on login. An empty list means the person is
   capped in nothing — show no counters at all.
2. For a product, check `restricted` first. If false, no badge, no blocking.
3. After each order, overwrite local state from `quota` in the response.
   Never increment locally.
4. Branch on `error`, not the status code.
5. If `requires_approval` is true, show the order as pending, not confirmed.

## 11. Model map

| Model | Fields | Role |
|---|---|---|
| `staff.allowance.rule` | 11 | One person + one POS category + a limit. All the logic. |
| `staff.allowance.plan` / `.plan.line` | 12 | Reusable tiers |
| `staff.allowance.order` | 15 | One consumption event; approval flow |
| `staff.allowance.usage` | 8 | Stored daily totals for reporting |
| `staff.allowance.attempt` | 10 | Refused orders |
| `staff.allowance.beneficiary.mixin` | 2 | Contact + timezone helpers |
| `pos.order` (inherited) | 3 | Records each sale against the customer's allowance |

Dropped in this version: the whole custom `staff.allowance.category` model
(20 fields) plus `assigned_only`, `fallback`, `unlimited`, `allowed`,
`applies_to`, `product_ids`, `origin`, `strict`, `code`, `color`, `note` on
plans, and `user_id` / `company_id` where nothing used them.

## 12. Install

Copy into your addons path, restart the service, **Apps → Update Apps List**,
install **Staff Allowance**. Depends on `hr` and `point_of_sale`, both
Community.

**Upgrading from 19.0.5.x** moves everything set on employees onto their work
contact: rules, orders, blocked attempts, and the plan when the contact has
none. Where the contact already had its own rule for a category, the
contact's rule is kept, since it is the one the POS was applying; the log
says how many employee rules that dropped.

**Restart the service on every upgrade.** Odoo re-reads XML on upgrade but
does not reload Python — model changes need a restart.

## 13. The POS cashier warning

`static/src/js/pos_allowance_warning.js` hooks into
`OrderPaymentValidation.askBeforeValidation()`, the step every validation goes
through — the payment screen's **Validate** and the quick payment buttons
alike. It calls `staff.allowance.rule.check_pos_basket()` with the customer
and the basket and shows the popup from section 5. The check records nothing;
recording happens on the server when the sale is paid.

If the check fails (server unreachable, unexpected data), the sale goes
through without a popup instead of leaving the cashier stuck.

It is loaded in `point_of_sale._assets_pos` and was checked against Odoo 19:
`@point_of_sale/app/utils/order_payment_validation` and
`@web/core/confirmation_dialog/confirmation_dialog`. If a future Odoo version
moves those, the POS screen fails to load; remove the `assets` block from
`__manifest__.py` and upgrade to get the POS back while it is fixed.

After upgrading, reload the POS page in the browser so it picks up the new
script.

## 14. Pre-flight check

```bash
cd staff_allowance && python3 tools/check_views.py
```

Validates every view against the models: fields exist (recursing into embedded
one2many subviews), no domain uses a non-stored field without a `search`
method, nothing groups by an unstored field, and every model with a search
view has a resolvable `_rec_name`.

## 15. Automated tests

`tests/test_allowance_api.py` calls the `/api/allowance/*` endpoints over real
HTTP with a logged-in user: rules, quota by product and by category, placing
orders (within the limit, over it with approval, in a free category), the
cancel rules, and history.

```bash
odoo -d YOUR_TEST_DB -u staff_allowance --test-tags /staff_allowance --stop-after-init
```

Use a test database. Everything a test creates is rolled back at the end.
