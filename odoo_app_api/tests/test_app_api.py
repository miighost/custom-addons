"""End-to-end tests of the mobile app API, over real HTTP.

    odoo -d YOUR_TEST_DB -u odoo_app_api --test-tags /odoo_app_api --stop-after-init
"""
import time

from cryptography.hazmat.primitives.asymmetric import rsa

from odoo import Command
from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.odoo_app_api.controllers import main

from .common import APPROVED, COMMITTED, AppApiCase

PHONE = "252611234567"


@tagged("post_install", "-at_install")
class TestAppApi(AppApiCase):

    # ------------------------------------------------------------------
    # authentication and profile
    # ------------------------------------------------------------------
    def test_token_is_required_and_verified(self):
        status, data = self._call("/api/v1/me", authenticated=False)
        self.assertEqual((status, data), (401, {"error": "Missing bearer token"}))

        other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        for label, token in (
            ("signed by another key", self._token(key=other_key)),
            ("expired", self._token(exp=int(time.time()) - 7200)),
            ("issued for another Firebase project", self._token(aud="another-project")),
            ("not a JWT", "not-a-token"),
        ):
            with self.subTest(label):
                status, data = self._call("/api/v1/me", token=token)
                self.assertEqual(status, 401, data)

    def test_me_creates_the_contact_once_with_a_membership_code(self):
        partner = self._me(email=f"new.{self.tag}@example.com", email_verified=True,
                           name="New Customer")
        self.assertEqual((partner.firebase_uid, partner.name), (self.firebase_uid, "New Customer"))
        self.assertTrue(partner.barcode)
        status, data = self._call("/api/v1/me")
        self.assertEqual(data["partner_id"], partner.id, "a second sign-in is the same contact")
        self.assertIn(f"/report/barcode/Code128/{partner.barcode}", data["barcode_image_url"])

    def test_me_claims_an_existing_contact_only_by_exact_verified_email(self):
        existing = self.env["res.partner"].create({
            "name": "Existing Customer", "email": f"john.smith.{self.tag}@example.com"})
        impostor = self._me(uid=f"impostor-{self.tag}", email_verified=True,
                            email=f"john_smith.{self.tag}@example.com")
        unverified = self._me(uid=f"unverified-{self.tag}", email_verified=False,
                              email=existing.email)
        self.assertNotEqual(impostor, existing, "_ must not act as a wildcard")
        self.assertNotEqual(unverified, existing, "an unverified email claims nothing")
        self.assertEqual(self._me(uid=f"owner-{self.tag}", email_verified=True,
                                  email=existing.email.upper()), existing)

    def test_me_update_changes_only_allowed_fields(self):
        partner = self._me()
        status, data = self._call("/api/v1/me/update", {
            "city": "Mogadishu", "email": f"hijack.{self.tag}@example.com"})
        self.assertEqual((status, data), (200, {"ok": True}))
        self.assertEqual(partner.city, "Mogadishu")
        self.assertNotEqual(partner.email, f"hijack.{self.tag}@example.com")

    # ------------------------------------------------------------------
    # catalogue and cart problems
    # ------------------------------------------------------------------
    def test_catalogue_lists_only_products_shown_in_the_app(self):
        self._me()
        status, data = self._call("/api/v1/products", {"search": self.tag, "limit": 50})
        listed = {product["id"]: product for product in data["products"]}
        self.assertIn(self.coffee.id, listed)
        self.assertNotIn(self.hidden.id, listed)
        self.assertEqual(listed[self.coffee.id]["price"], 10.0)
        self.assertIn("reason", self._call("/api/v1/products", {"search": f"none-{self.tag}"})[1]["hint"])
        self.assertTrue(self._call("/api/v1/categories")[1]["categories"])
        self.assertEqual(self.url_open(f"/api/v1/product/{self.coffee.id}/image").status_code, 200)
        self.assertEqual(self.url_open(f"/api/v1/product/{self.hidden.id}/image").status_code, 404)

    def test_cart_problems_are_named(self):
        self._me()
        for body, error in (
            ({"lines": []}, "no_lines"),
            ({"lines": [{"product_id": self.coffee.id, "qty": 0}]}, "bad_qty"),
            ({"lines": [{"product_id": self.coffee.id, "qty": "two"}]}, "bad_lines"),
            ({"lines": [{"product_id": 999999999}]}, "unknown_product"),
            ({"lines": [{"product_id": self.hidden.id}]}, "product_not_orderable"),
        ):
            with self.subTest(error):
                self.assertEqual(self._call("/api/v1/checkout", {**body, "payment": "account"})[1],
                                 {"error": error})
        self.assertEqual(self._checkout("cash", 1)[1], {"error": "unknown_payment_method"})

    def test_malformed_body_is_a_clean_400(self):
        response = self.url_open("/api/v1/checkout", data="{not json", method="POST",
                                 headers={"Authorization": f"Bearer {self._token()}",
                                          "Content-Type": "application/json"})
        self.assertEqual((response.status_code, response.json()), (400, {"error": "bad_request"}))

    def test_a_failing_call_saves_nothing(self):
        self._me()

        def broken(*args, **kwargs):
            raise RuntimeError("database password is hunter2")

        self.patch(main.AppApi, "_order_dict", broken)
        with mute_logger("odoo.addons.odoo_app_api.controllers.main"):
            status, data = self._call("/api/v1/orders/create", {
                "client_ref": f"rollback-{self.tag}",
                "lines": [{"product_id": self.coffee.id, "qty": 1}]})
        self.assertEqual((status, data), (400, {"error": "server_error"}))
        self.assertFalse(self.env["sale.order"].search(
            [("client_order_ref", "=", f"rollback-{self.tag}")]))

    # ------------------------------------------------------------------
    # checkout
    # ------------------------------------------------------------------
    def test_payment_methods(self):
        partner = self._me()
        self._card(partner, 25)
        methods = {m["code"]: m for m in self._call("/api/v1/payment/methods")[1]["methods"]}
        self.assertEqual(set(methods), {"wallet", "account", "waafi"})
        self.assertEqual((methods["wallet"]["available"], methods["wallet"]["balance"]), (True, 25))
        self.assertTrue(methods["account"]["available"])
        self.assertIsNone(methods["account"]["credit_limit"])
        self.assertTrue(methods["waafi"]["available"])

    def test_checkout_with_the_wallet(self):
        partner = self._me()
        card = self._card(partner, 50)
        status, data = self._checkout("wallet", 3)
        self.assertEqual(status, 200, data)
        self.assertTrue(data["paid"])
        order = data["order"]
        self.assertEqual((order["state"], order["payment_method"], order["payment_status"]),
                         ("sale", "wallet", "paid"))
        self.assertTrue(order["invoice_ids"], "the paid order is invoiced")
        self.assertEqual((data["balance_after"], card.points), (20, 20))

    def test_checkout_with_too_little_in_the_wallet_saves_nothing(self):
        partner = self._me()
        card = self._card(partner, 10)
        before = self._orders_of(partner)
        status, data = self._checkout("wallet", 3)
        self.assertEqual(data, {"error": "insufficient_balance", "amount_due": 30.0,
                                "wallet_balance": 10, "missing": 20.0})
        self.assertEqual(self._orders_of(partner), before, "no stray quotation")
        self.assertEqual(card.points, 10)

    def test_checkout_on_account_invoices_and_respects_the_credit_limit(self):
        partner = self._me()
        status, data = self._checkout("account", 3)
        self.assertEqual(status, 200, data)
        self.assertEqual((data["paid"], data["amount_due"]), (False, 30.0))
        self.assertEqual((data["order"]["payment_method"], data["order"]["payment_status"]),
                         ("account", "to_pay"))
        unpaid = self._call("/api/v1/invoices", {"only_unpaid": True})[1]["invoices"]
        self.assertIn(data["invoice_id"], [invoice["id"] for invoice in unpaid],
                      "the order shows on the Balance page")

        self.env.company.account_use_credit_limit = True
        partner.write({"use_partner_credit_limit": True, "credit_limit": 40})
        before = self._orders_of(partner)
        status, data = self._checkout("account", 3)
        self.assertEqual(data["error"], "credit_limit_exceeded", data)
        self.assertTrue(data["message"])
        self.assertEqual(self._orders_of(partner), before)

    def test_checkout_by_waafipay(self):
        self._me()
        calls = self._fake_gateway(APPROVED, COMMITTED)
        status, data = self._checkout("waafi", 2, phone=PHONE)
        self.assertEqual(status, 200, data)
        self.assertTrue(data["paid"])
        self.assertEqual(calls, ["API_PREAUTHORIZE", "API_PREAUTHORIZE_COMMIT"])
        self.assertEqual((data["order"]["payment_method"], data["order"]["payment_status"]),
                         ("waafi", "paid"))

    def test_declined_checkout_saves_nothing(self):
        partner = self._me()
        self._fake_gateway({"responseCode": "5206", "responseMsg": "Customer rejected"})
        before = self._orders_of(partner)
        self.assertEqual(self._checkout("waafi", 1, phone=PHONE)[1],
                         {"error": "payment_declined", "gateway_message": "Customer rejected"})
        self.assertEqual(self._orders_of(partner), before)

    # ------------------------------------------------------------------
    # order history
    # ------------------------------------------------------------------
    def test_order_history_and_detail(self):
        partner = self._me()
        placed = self._checkout("account", 1)[1]["order"]
        listed = {o["id"]: o for o in self._call("/api/v1/orders")[1]["orders"]}
        self.assertEqual(listed[placed["id"]]["payment_status"], "to_pay")

        status, data = self._call("/api/v1/orders/detail", {"order_id": placed["id"]})
        self.assertEqual((data["amount_due"], len(data["lines"])), (10.0, 1))

        someone_else = self.env["sale.order"].create({
            "partner_id": self.env["res.partner"].create({"name": "Someone Else"}).id,
            "order_line": [Command.create({"product_id": self.coffee.id})]})
        self.assertNotIn(someone_else.id, listed)
        self.assertEqual(self._call("/api/v1/orders/detail", {"order_id": someone_else.id})[1],
                         {"error": "order_not_found"})

    # ------------------------------------------------------------------
    # earlier routes still used for existing quotations
    # ------------------------------------------------------------------
    def test_wallet_pay_on_an_existing_quotation(self):
        partner = self._me()
        self._card(partner, 40)
        order = self._order(3)
        status, data = self._call("/api/v1/wallet/pay", {"order_id": order.id, "confirm": True})
        self.assertEqual(status, 200, data)
        self.assertTrue(data["fully_covered"] and data["confirmed"])
        self.assertEqual(data["order"]["payment_status"], "paid")
        self.assertEqual(self._call("/api/v1/wallet/pay", {"order_id": order.id})[1]["error"],
                         "order_not_editable")

    def test_pay_an_existing_quotation_by_waafipay_once(self):
        self._me()
        order = self._order(1)
        calls = self._fake_gateway(APPROVED, COMMITTED)
        status, data = self._call("/api/v1/pay", {"order_id": order.id, "phone": PHONE})
        self.assertEqual(status, 200, data)
        self.assertEqual((order.state, order.app_payment_reference), ("sale", "TX-TEST"))
        self.assertEqual(data["order"]["payment_status"], "paid")
        self.assertEqual(self._call("/api/v1/pay", {"order_id": order.id, "phone": PHONE})[1]["error"],
                         "already_paid")
        self.assertEqual(len(calls), 2, "a second tap never reaches the gateway")

    def test_topup(self):
        self._me()
        self.assertIn(self.topup_product.id,
                      [p["id"] for p in self._call("/api/v1/wallet/topup/products")[1]["products"]])
        status, data = self._call("/api/v1/wallet/topup", {"product_id": self.topup_product.id})
        self.assertEqual((data["order"]["state"], data["order"]["amount_total"]), ("draft", 50.0))
        self.assertEqual(self._call("/api/v1/wallet/topup", {"product_id": self.coffee.id})[1]["error"],
                         "not_a_topup_product")

    # ------------------------------------------------------------------
    # balance page
    # ------------------------------------------------------------------
    def test_summary_and_invoices_are_scoped_to_the_customer(self):
        partner = self._me()
        overdue = self._invoice(partner, 100, days_overdue=10)
        current = self._invoice(partner, 50)
        someone_else = self._invoice(self.env["res.partner"].create({"name": "Someone Else"}), 70)
        self._card(partner, 30)

        data = self._call("/api/v1/summary")[1]
        self.assertEqual((data["total_due"], data["overdue"], data["open_invoice_count"],
                          data["wallet_balance"]), (150.0, 100.0, 2, 30))
        listed = {i["id"]: i for i in self._call("/api/v1/invoices", {"only_unpaid": True})[1]["invoices"]}
        self.assertEqual(set(listed), {overdue.id, current.id})
        self.assertTrue(listed[overdue.id]["overdue"])
        self.assertEqual(self._call("/api/v1/invoices/detail", {"invoice_id": someone_else.id})[1],
                         {"error": "invoice_not_found"})

    def test_pay_selected_invoices(self):
        partner = self._me()
        first = self._invoice(partner, 100, days_overdue=5)
        second = self._invoice(partner, 50)
        third = self._invoice(partner, 30)
        card = self._card(partner, 60)

        selected = {"invoice_ids": [first.id, second.id]}
        self.assertEqual(self._call("/api/v1/invoices/pay", {**selected, "method": "wallet"})[1],
                         {"error": "insufficient_balance", "amount_due": 150.0,
                          "wallet_balance": 60, "missing": 90.0})
        self.assertEqual(card.points, 60, "a wallet too low is not touched")

        calls = self._fake_gateway(APPROVED, COMMITTED)
        status, data = self._call("/api/v1/invoices/pay", {**selected, "method": "waafi", "phone": PHONE})
        self.assertEqual(status, 200, data)
        self.assertEqual((data["paid"], data["amount_paid"]), (True, 150.0))
        self.assertEqual(calls, ["API_PREAUTHORIZE", "API_PREAUTHORIZE_COMMIT"],
                         "one charge, one approval on the phone, for both invoices")
        self.assertEqual((first.amount_residual, second.amount_residual, third.amount_residual),
                         (0.0, 0.0, 30.0))

        self.assertEqual(self._call("/api/v1/invoices/pay", {"invoice_ids": [first.id]})[1],
                         {"error": "not_payable", "invoices": [first.name]})
        someone_else = self._invoice(self.env["res.partner"].create({"name": "Someone Else"}), 70)
        self.assertEqual(self._call("/api/v1/invoices/pay", {"invoice_ids": [someone_else.id]})[1],
                         {"error": "invoice_not_found"})

    def test_clear_pays_everything_open_at_once(self):
        partner = self._me()
        first = self._invoice(partner, 100, days_overdue=5)
        second = self._invoice(partner, 50)
        card = self._card(partner, 120)

        self.assertEqual(self._call("/api/v1/invoices/clear", {"method": "wallet"})[1]["missing"], 30.0)

        card.points = 150
        status, data = self._call("/api/v1/invoices/clear", {"method": "wallet"})
        self.assertEqual(status, 200, data)
        self.assertEqual((data["cleared"], data["amount_paid"], data["balance_after"]), (True, 150.0, 0))
        self.assertEqual((first.amount_residual, second.amount_residual), (0.0, 0.0))
        self.assertEqual(self._call("/api/v1/invoices/clear", {"method": "wallet"})[1],
                         {"cleared": True, "paid": False, "amount_paid": 0.0, "invoices": []})
