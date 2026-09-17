# App API: Staff Allowance — Odoo 19

Connects **App API (Firebase)** and **Staff Allowance**. It installs itself
when both are installed; there is nothing to configure.

| What | How |
|---|---|
| `POST /api/v1/allowance` | The customer's daily limits: `limits[]` with `category`, `limit`, `used`, `remaining`, `at_the_limit`, `from_plan`, `resets_at`. |
| `/api/v1/products` | Every product carries `allowance`: `{"restricted": false}`, or the tightest limit it counts against with `remaining`, so the app can show "2 left today". |
| `/api/v1/checkout` | Checks the cart like the POS does at Validate. **Block** (or tolerance used up) → `allowance_limit_reached` with `messages`, nothing saved, logged in Blocked Attempts. The other policies → the order goes through with `allowance_warnings`. |
| Confirmed app orders | Count against the allowance (source *Mobile App*, linked to the sales order). Cancelling the order gives it back. |

Limits are set in Odoo exactly as for the POS: **Allowances → People → Give an
Allowance**.

```bash
odoo -d YOUR_TEST_DB -u odoo_app_api_allowance --test-tags /odoo_app_api_allowance --stop-after-init
```
