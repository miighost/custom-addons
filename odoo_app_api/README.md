# App API (Firebase) — Odoo 19

Bridges a FlutterFlow app that uses **Firebase Authentication** to an Odoo 19
Community backend. Firebase owns identity; Odoo owns the data.

```
FlutterFlow  --Firebase ID token-->  Odoo controller
                                       |  verifies the JWT against Google's
                                       |  public certs (no extra libraries)
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

1. Copy this folder into your addons path, restart Odoo, update the app list,
   install **App API (Firebase)**.

2. **Settings → Mobile App** → fill in the Firebase Project ID, and the
   WaafiPay credentials when you get to payments. (These are also visible
   as `app_api.*` system parameters, but the Settings page is the place to
   edit them.)

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
**Show in Mobile App**.

That last one is **on by default for every product**, existing ones included —
there is nothing to switch on. It exists only so you can HIDE something:
untick it and that product disappears from the app while staying available
everywhere else in Odoo (internal services, staff-only items, a product you
are not ready to publish).

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

---

## Linking existing customers to app accounts

Three ways, in order of preference.

### 1. Automatic (do nothing)

On a customer's first sign-in the module tries, in order:

1. a contact already carrying that Firebase UID;
2. an **unlinked** contact whose email matches the token's email — only when
   Firebase reports `email_verified: true`;
3. an **unlinked** contact whose phone or mobile matches the token's phone;
4. otherwise a new contact is created.

So the cheapest preparation is simply to make sure your existing contacts have
the right email address. The customer signs up with that email, verifies it,
and the accounts join themselves.

Unverified emails are never matched. Otherwise anyone could sign up as
`bigcustomer@example.com` and inherit that company's orders and wallet.

### 2. Manual, before they sign up

Nothing to do — see above. Just fix the email on the contact.

### 3. Manual, after a duplicate already exists

Two situations:

**The customer signed up and got a NEW contact, and the old one still exists.**
Use Odoo's built-in merge: Contacts → tick both records → **Actions → Merge
Contacts** → choose the one to keep → Merge. Orders, invoices and the Firebase
UID all follow to the surviving record.

**You want to link a contact by hand.** Open the contact → **Mobile App** tab →
paste the Firebase UID into **Firebase UID** → Save. Find the UID in the
Firebase console under **Authentication → Users**, column **User UID** (a
28-character string like `k3Jd8sLp...`). The field is unique, so Odoo refuses a
UID that is already on another contact — that error means you should merge
rather than link.

Clear the field to unlink; the next sign-in will create a fresh contact.

---

## Paying from the app

```
POST /api/v1/pay   {"order_id": 123, "phone": "25261xxxxxxx"}
```

Odoo calls WaafiPay itself: `API_PREAUTHORIZE` (customer approves on their
handset), then `API_PREAUTHORIZE_COMMIT`. The order is confirmed only when the
gateway's own answer says the money moved. The transaction id is written to
**App Payment Reference** on the order and posted to the chatter.

**Do not call WaafiPay from FlutterFlow.** Two reasons:

1. The merchant `apiKey` would sit inside your published APK/IPA, where anyone
   can extract it and charge your merchant account.
2. An app that reports its own payment as successful is an app that can be
   modified to lie. Only the server may decide an order is paid.

Set the credentials in **Settings → Mobile App → WaafiPay**:

| Field | Value |
|---|---|
| API URL | `https://sandbox.waafipay.com/asm` (prod: `https://api.waafipay.net/asm`) |
| Merchant UID | from your WaafiPay merchant account |
| API User ID | " |
| API Key | " (stored masked; never goes near the app) |

Test on sandbox first. Switch `app_api.waafi_url` to production only once a
sandbox payment confirms an order end to end.

The call blocks while the customer approves on their phone, so set the
FlutterFlow API call timeout to at least 60 seconds and show a spinner.

### Paying a top-up

Identical: `/api/v1/wallet/topup` creates the order, then `/api/v1/pay` with
that order id. Confirming a top-up order is what credits the eWallet, so the
balance appears the moment the gateway commits.

---

## Membership barcode

`/api/v1/me` returns a scannable code for the customer:

```json
{
  "barcode": "JPH000016",
  "barcode_image_url": "https://…/report/barcode/Code128/JPH000016?width=600&height=150&humanreadable=1",
  "qr_image_url": "https://…/report/barcode/QR/JPH000016?width=400&height=400"
}
```

The code is generated on the customer's first sign-in as `<prefix><partner id>`
padded to six digits. Change the prefix in **Settings → Mobile App →
Membership Code Prefix**; it applies to customers who sign up after the change.
Staff can read or overwrite it on the contact's **Mobile App** tab.

It is Odoo's standard `res.partner.barcode` field, so anything that already
scans contacts — Point of Sale, a barcode scanner on the contacts list —
recognises it without further setup.

The two image URLs are absolute and use Odoo's built-in public barcode
renderer, so an `Image` widget can load them with no token. They are built
from `web.base.url`, so make sure that system parameter is your real HTTPS
domain and not `localhost:8069`.

---

## Account: what they owe, and clearing it

| Route | Body | Returns |
|---|---|---|
| `/api/v1/summary` | `{}` | one call for the home screen |
| `/api/v1/invoices` | `{"only_unpaid":true,"limit":20}` | invoice list |
| `/api/v1/invoices/detail` | `{"invoice_id":42}` | one invoice with its lines |
| `/api/v1/invoices/pay` | `{"invoice_id":42,"method":"wallet"}` | pay one invoice |
| `/api/v1/invoices/clear` | `{"method":"wallet"}` | pay every open invoice, oldest first |

`/api/v1/summary` is the one to build the home screen on — it replaces four
separate calls:

```json
{
  "name": "Cabdi Trading",
  "barcode": "JPH000016",
  "barcode_image_url": "https://…/report/barcode/Code128/JPH000016?…",
  "wallet_balance": 250.0,
  "total_due": 1840.5,
  "overdue": 640.0,
  "credit_notes": 0.0,
  "open_invoice_count": 3,
  "can_clear_with_wallet": false,
  "currency": "SOS"
}
```

`can_clear_with_wallet` is the flag to enable or grey out the "Pay from
wallet" button — the app never has to do that arithmetic itself.

### Paying

`method` is `"wallet"` or `"waafi"`. Both register a real
`account.payment` through Odoo's own payment-register wizard, so the invoice
reconciles exactly as it would if your accountant had done it by hand — the
payment shows in the journal, on the invoice, and in the customer's
statement.

Add `"amount": 500` to pay part of an invoice; leave it out to pay the
balance in full. Paying from the wallet also debits the loyalty card and
writes a `loyalty.history` line, so the wallet ledger and the accounting
entry always agree.

`/api/v1/invoices/clear` walks the open invoices oldest-first and **stops at
the first failure** rather than continuing to charge a customer whose payment
is already failing. Read `failed[0].error` to see why it stopped.

### Configure the journals first

**Settings → Mobile App → Accounting**

| Field | Point it at |
|---|---|
| eWallet Journal | a journal whose account is your customer-wallet liability account |
| WaafiPay Journal | the bank/cash journal your WaafiPay settlements land in |

If either is blank the module falls back to the first bank or cash journal it
finds, which will book the money in the wrong place. Set them.

### Scoping

Every route here builds its domain from the Firebase-resolved partner:

    ('partner_id', 'child_of', partner.commercial_partner_id.id)

An invoice id is only ever looked up *inside* that domain, never with
`browse()`. So incrementing an id in the request body returns
`invoice_not_found`, not someone else's invoice.

---

## The Mobile App menu in Odoo

Installing the module adds a top-level **Mobile App** menu for your staff:

```
Mobile App
├── Operations
│   ├── Orders      sale.order where is_app_order = True
│   ├── Invoices    customer invoices of app users
│   └── eWallets    every ewallet loyalty.card, with a balance total
├── Customers
│   └── App Customers   contacts carrying a Firebase UID
└── Configuration
    └── Settings    Firebase, WaafiPay, journals, code prefix
```

Nothing here is a separate copy of your data. These are filtered views of the
real `sale.order`, `account.move`, `loyalty.card` and `res.partner` records —
the same ones Sales and Accounting show. An order opened from this menu is the
same order your sales team sees, with the standard form.

**Orders** opens on quotations by default, since those are the ones needing
attention. Clear the filter to see confirmed orders. The list carries
**Paid With** and **Reference** columns so you can tell an eWallet order from
a WaafiPay one at a glance, and the search panel groups by payment method.

**eWallets** sums the Balance column — that total is what you reconcile
against your customer-wallet liability account.

**App Customers** shows the membership code beside each contact, so a customer
reading their code over the phone can be found instantly.

Orders placed through the app are flagged with `is_app_order`, set by the API
at creation. Existing orders made before this version are not flagged; if you
want them listed, set the flag on them once:

```python
env['sale.order'].search([('origin', 'like', 'Mobile app')]).write(
    {'is_app_order': True})
```

## Dashboard

Clicking **Mobile App** in the menu bar lands on a dashboard built from live
records — no stored snapshot, nothing to refresh:

| Section | Shows |
|---|---|
| Today | orders confirmed, their value, orders this week |
| Needs attention | quotations awaiting confirmation, overdue invoice total |
| Money | eWallet balances held (money you owe), outstanding from app customers |
| Customers | app users, and how many joined in the last 7 days |

Every card's button opens the real records behind the number, pre-filtered —
"Chase overdue" opens exactly the overdue invoices it counted, so the figure
and the list can never disagree.

The two figures to watch are **eWallet balances held** (reconcile it against
your wallet liability account) and **Overdue** (money already earned and not
collected).

---

## JPH Wallet (back office)

A dedicated section under **Mobile App → JPH Wallet**:

| Menu | What it is |
|---|---|
| Wallets | every customer wallet, with balance, topped-up and spent totals, last movement, and a **Total Held** sum |
| Top Up Wallet | the wizard for crediting a customer at the counter |
| Transactions | the wallet ledger — every credit and debit, with In/Out totals |
| Configuration → Wallet Programs | the eWallet programs themselves |

Nothing here is a new wallet model. It is Odoo's own `loyalty.card` /
`loyalty.history`, filtered to eWallet programs and given a wallet-shaped
list. So the Point of Sale, the portal and the app all see the same balances.

### Topping up at the counter

**Mobile App → JPH Wallet → Top Up Wallet** (or the **Top Up Wallet** entry in
the Actions menu of any wallet).

Pick the customer, the amount, and the journal the money went into. The wizard
then does what Odoo would have you do by hand:

1. creates a sale order for the program's top-up product with the line price
   set to your amount;
2. confirms it — **this is the step that credits the wallet**, because an
   eWallet rule awards points equal to the money spent on its trigger product;
3. invoices it and registers the payment, when *Customer is paying now* is
   ticked.

The result is one balance, one journal entry and one customer statement that
all agree. Untick *Customer is paying now* to leave the invoice open for a
customer paying later — the balance is credited either way, which is a credit
decision your team makes deliberately rather than by accident.

The wizard refuses a product that is not listed in the program's **eWallet
Products**, since Odoo would silently credit nothing in that case.

Access is limited to Sales users and Invoicing users — topping up a wallet
creates a liability, so it is not something every internal user should do.
