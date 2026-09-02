# App API (Firebase) — Odoo 19

Bridges a FlutterFlow app that uses **Firebase Authentication** to an Odoo 19
Community backend. Firebase owns identity; Odoo owns the data.

```
FlutterFlow  --Firebase ID token-->  Odoo controller
                                       |  verifies the JWT against Google's
                                       |  public certs (no firebase-admin)
                                       v
                                     res.partner (firebase_uid)
                                       |
                                       +-- loyalty.card   (eWallet balance)
                                       +-- sale.order     (visible to staff)
```

No Odoo portal users, no per-customer API keys. The Firebase ID token *is*
the credential; the partner is resolved server-side from its claims, so the
app can never ask for someone else's data.

## Install

1. On the Odoo server:

       pip install PyJWT cryptography requests

2. Copy this folder into your addons path, restart Odoo, update the app list,
   install **App API (Firebase)**.

3. Settings → Technical → System Parameters → set
   `app_api.firebase_project_id` to your Firebase project id
   (Firebase console → Project settings → Project ID).

## Endpoints

All are `POST`, all take `Authorization: Bearer <firebase_id_token>`.

| Route | Body | Returns |
|---|---|---|
| `/api/v1/me` | `{}` | profile; creates/links the contact on first call |
| `/api/v1/me/update` | `{"phone":"...","city":"..."}` | `{"ok":true}` |
| `/api/v1/wallet` | `{}` | `balance`, `currency`, `transactions[]` |
| `/api/v1/orders` | `{"limit":20,"offset":0}` | `orders[]` |
| `/api/v1/orders/create` | `{"lines":[{"product_id":42,"qty":2}]}` | the created order |

Errors come back as `{"error": "..."}` with a real HTTP status (401 for a bad
or missing token, 400 otherwise) — no JSON-RPC envelope, so FlutterFlow JSON
paths are flat: `$.balance`, `$.orders[:].name`.

## How the contact is linked

`/api/v1/me` resolves the token claims to exactly one `res.partner`:

1. match on `firebase_uid` — returning user, done;
2. else match a contact by **verified** email, or by phone — a customer who
   already existed in Odoo gets claimed rather than duplicated;
3. else create a new contact with `customer_rank = 1`.

The uid is then stored on the contact (unique constraint), visible to staff
on the contact form under the **Mobile App** tab, with an **App Users** filter
in the Contacts search panel.

Unverified emails are deliberately not used for matching — otherwise anyone
could sign up with your best customer's address and inherit their records.

## Staff side

Orders from the app are ordinary `sale.order` records with `origin = "Mobile
app"` and a chatter note, landing in Sales → Orders → Quotations. They are
left as quotations so staff confirm them; call `action_confirm()` in
`order_create` if the app should place firm orders instead.

## FlutterFlow wiring

Custom Action to get a fresh token (they expire after 1 hour, so fetch per
call rather than caching):

```dart
// Custom Action: getFirebaseToken
import 'package:firebase_auth/firebase_auth.dart';

Future<String?> getFirebaseToken() async {
  final user = FirebaseAuth.instance.currentUser;
  if (user == null) return null;
  return await user.getIdToken();
}
```

Then on each API Call define a String variable `authToken` and set the header:

    Authorization: Bearer <authToken>

Call `/api/v1/me` once right after sign-in so the contact exists in Odoo
before any other screen loads.

## Reverse proxy note

If you front Odoo with nginx and call the API from FlutterFlow **web**, add:

    add_header Access-Control-Allow-Headers "Authorization, Content-Type" always;

Native iOS/Android builds do not send preflight requests, so this only
matters for web/test mode.

---

## eWallet: spending and topping up

In Odoo an eWallet is not a payment method — it is a loyalty program whose
reward discounts the order total. So "paying with the wallet" means applying
a reward to a quotation, which keeps every movement inside `loyalty.history`
where staff and accounting can reconcile it.

| Route | Body | Does |
|---|---|---|
| `/api/v1/wallet/pay` | `{"order_id":123,"confirm":true}` | applies the balance to that order |
| `/api/v1/wallet/topup/products` | `{}` | lists the configured top-up products |
| `/api/v1/wallet/topup` | `{"product_id":55,"qty":1}` | creates a top-up order |

`wallet/pay` always returns what actually happened rather than a bare ok:

```json
{
  "wallet_applied": 40.0,
  "remaining_due": 12.5,
  "fully_covered": false,
  "balance_after": 0.0,
  "confirmed": false,
  "order": { "...": "..." }
}
```

Partial coverage is the normal case, not an edge case — a $52.50 order against
a $40 balance leaves $12.50 due. The app should read `remaining_due` and route
to your payment provider when it is above zero. The order is only confirmed
when `confirm: true` **and** the wallet covered the whole total.

Orders are looked up with a domain scoped to the caller's partner, never
`browse(order_id)` — otherwise incrementing an id in the request body would
let one customer spend their wallet on someone else's order.

### Configure the program first

Sales → Products → Gift cards & eWallet → New → type **eWallet**:

1. Create service products for each top-up amount ("$50 Top-Up", price 50).
2. List them in **eWallet Products** on the program.
3. Leave the reward as the default discount on the order total.

`topup/products` reads those products off the program, so the app's top-up
screen stays in sync with Odoo without a second config.

### The accounting bit — get this right before go-live

A top-up is **not revenue**. The customer has handed you money for goods not
yet delivered, which is a liability until they spend it. If the top-up product
posts to a normal income account, you book revenue at top-up *and* again when
they order — the same money counted twice.

Set it up so the wallet nets to zero:

- Create an account like **Customer Wallet Liability** (current liabilities).
- Top-up product → Accounting tab → **Income Account** = that liability account.
- The eWallet program's discount product (Products → search the program's
  discount product, or `payment_program_discount_product_id`) → **Income
  Account** = the same liability account.

Top-up credits the liability, spending debits it, and revenue is recognised
once, on the real order line. Check the balance of that account against
`SUM(loyalty.card.points)` monthly — they should match, and a drift means
someone adjusted a card by hand.

Wallet balances are also a deposit you owe. Expiry dates, refundability and
whether unspent balances escheat are regulated differently in different
places — worth a word with your accountant before you take real top-ups.

---

## Catalogue

| Route | Body | Returns |
|---|---|---|
| `/api/v1/products` | `{"search":"","category_id":null,"limit":30,"offset":0}` | `total`, `products[]` |
| `/api/v1/categories` | `{}` | categories with product counts |
| `/api/v1/product/<id>/image` | *(GET, no token)* | the product image, cached 24h |

A product appears in the app when it is **active**, **Can be Sold**, and
**Available in App** — a checkbox this module adds next to "Can be Sold" on
the product form, with a matching "In Mobile App" filter in the product
search panel. Untick it to pull something from the app without affecting the
rest of Odoo.

Prices come from the **customer's own pricelist**
(`partner.property_product_pricelist`), not `list_price` — so B2B customers on
a negotiated pricelist see their prices, and the figure in the app matches
what the order will actually total. Currency follows the pricelist too.

`/api/v1/orders/create` re-checks the same three flags server-side, so a
product pulled from the app cannot still be ordered by an app holding a stale
catalogue.

### Images

The image route is deliberately **not** token-protected, so FlutterFlow's
`Image.network` widget can load it directly without a custom header — but it
only ever serves products that pass the catalogue filter. Put the returned
`image_url` behind your base URL:

    https://erp.yourdomain.com/api/v1/product/42/image

Add `?size=128` (128 / 256 / 512 / 1024) for list thumbnails; the default is
512. `has_image` tells the app whether to show a placeholder instead.

### Stock

`in_stock` is `qty_available > 0` for storable products, and always `true` for
services and consumables. It is a display hint, not a reservation — two
customers can both be told "in stock" for the last unit. If you need real
availability, confirm the order and let Odoo's stock rules do it.
