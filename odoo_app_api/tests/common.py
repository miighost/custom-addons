"""Shared set-up for mobile app API tests.

Firebase ID tokens are signed with a key generated for the test run, and the
module is told to trust that key instead of Google's certificates. WaafiPay is
replaced by a fake gateway. Everything else - routing, token checks, access
scoping, the database - is the real thing.
"""
import base64
import json
import time
import uuid

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from odoo import Command, fields
from odoo.tests import HttpCase

from odoo.addons.odoo_app_api.controllers import firebase, payment

PROJECT = "app-api-test"
KID = "test-signing-key"
APPROVED = {"responseCode": "2001", "params": {"transactionId": "TX-TEST"}}
COMMITTED = {"responseCode": "2001"}


def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class AppApiCase(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.tag = uuid.uuid4().hex[:6]

        params = cls.env["ir.config_parameter"].sudo()
        params.set_param("app_api.firebase_project_id", PROJECT)
        cls.bank = cls.env["account.journal"].search([
            ("type", "=", "bank"), ("company_id", "=", cls.env.company.id)], limit=1)
        params.set_param("app_api.wallet_journal_id", cls.bank.id)
        params.set_param("app_api.waafi_journal_id", cls.bank.id)
        params.set_param("app_api.waafi_url", "https://gateway.invalid/asm")
        params.set_param("app_api.waafi_merchant_uid", "TEST-MERCHANT")
        cls.env.company.account_use_credit_limit = False

        Product = cls.env["product.product"]
        cls.coffee = Product.create({
            "name": f"Coffee {cls.tag}", "list_price": 10.0, "sale_ok": True,
            "taxes_id": [Command.clear()]})
        cls.hidden = Product.create({
            "name": f"Hidden {cls.tag}", "list_price": 5.0, "sale_ok": True,
            "available_in_app": False, "taxes_id": [Command.clear()]})
        cls.topup_product = Product.create({
            "name": f"Top-up {cls.tag}", "type": "service", "list_price": 50.0,
            "taxes_id": [Command.clear()]})
        cls.wallet_program = cls.env["loyalty.program"].create({
            "name": f"Wallet {cls.tag}", "program_type": "ewallet",
            "trigger": "auto", "applies_on": "future",
            "reward_ids": [Command.create({
                "reward_type": "discount", "discount_mode": "per_point", "discount": 1})],
            "rule_ids": [Command.create({
                "reward_point_amount": 1, "reward_point_mode": "money",
                "product_ids": cls.topup_product.ids})],
            "trigger_product_ids": cls.topup_product.ids,
        })

    def setUp(self):
        super().setUp()
        # The app sends no cookie, so Odoo must find the database by itself.
        # On a server with one database (or a db-filter) it does; the test
        # server hosts several, so pin an anonymous session to the test one.
        self.authenticate(None, None)
        public_key = self.key.public_key()
        self.patch(firebase, "_load_public_keys", lambda force=False: {KID: public_key})
        self.firebase_uid = f"uid-{uuid.uuid4().hex[:12]}"

    # ------------------------------------------------------------------
    def _token(self, uid=None, key=None, **claims):
        now = int(time.time())
        uid = uid or self.firebase_uid
        payload = {
            "aud": PROJECT, "iss": f"https://securetoken.google.com/{PROJECT}",
            "sub": uid, "user_id": uid, "iat": now, "auth_time": now,
            "exp": now + 3600, **claims,
        }
        header = {"alg": "RS256", "kid": KID, "typ": "JWT"}
        signing_input = (f"{_b64(json.dumps(header).encode())}."
                         f"{_b64(json.dumps(payload).encode())}")
        signature = (key or self.key).sign(
            signing_input.encode(), padding.PKCS1v15(), hashes.SHA256())
        return f"{signing_input}.{_b64(signature)}"

    def _call(self, route, body=None, token=None, authenticated=True):
        headers = {"Authorization": f"Bearer {token or self._token()}"} if authenticated else {}
        response = self.url_open(route, json=body or {}, headers=headers, method="POST")
        return response.status_code, response.json()

    def _me(self, uid=None, **claims):
        status, data = self._call("/api/v1/me", token=self._token(uid=uid, **claims))
        self.assertEqual(status, 200, data)
        return self.env["res.partner"].browse(data["partner_id"])

    def _order(self, qty):
        status, data = self._call("/api/v1/orders/create", {
            "lines": [{"product_id": self.coffee.id, "qty": qty}]})
        self.assertEqual(status, 200, data)
        return self.env["sale.order"].browse(data["id"])

    def _checkout(self, payment_method, qty, **extra):
        return self._call("/api/v1/checkout", {
            "lines": [{"product_id": self.coffee.id, "qty": qty}],
            "payment": payment_method, **extra})

    def _card(self, partner, points):
        return self.env["loyalty.card"].create({
            "program_id": self.wallet_program.id, "partner_id": partner.id,
            "points": points})

    def _invoice(self, partner, amount, days_overdue=0):
        today = fields.Date.context_today(self.env.user)
        move = self.env["account.move"].create({
            "move_type": "out_invoice", "partner_id": partner.id,
            "invoice_date": fields.Date.subtract(today, days=30 + days_overdue),
            "invoice_date_due": fields.Date.subtract(today, days=days_overdue) if days_overdue
            else fields.Date.add(today, days=30),
            "invoice_line_ids": [Command.create({
                "name": "Service", "quantity": 1, "price_unit": amount,
                "tax_ids": [Command.clear()]})],
        })
        move.action_post()
        return move

    def _orders_of(self, partner):
        return self.env["sale.order"].search_count([("partner_id", "=", partner.id)])

    def _fake_gateway(self, *responses):
        """Replace WaafiPay: answers come from `responses`, calls are recorded."""
        calls, answers = [], list(responses)

        def fake_waafi(service_name, service_params, timeout=None):
            calls.append(service_name)
            return answers.pop(0)

        self.patch(payment, "_waafi", fake_waafi)
        return calls
