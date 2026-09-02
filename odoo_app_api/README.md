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
