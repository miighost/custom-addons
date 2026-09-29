"""The allowance in the mobile app, over real HTTP.

    odoo -d YOUR_TEST_DB -u odoo_app_api_allowance --test-tags /odoo_app_api_allowance --stop-after-init
"""
from odoo import Command
from odoo.tests import tagged

from odoo.addons.odoo_app_api.tests.common import AppApiCase


@tagged("post_install", "-at_install")
class TestAppAllowance(AppApiCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.drinks = cls.env["pos.category"].create({"name": f"Drinks {cls.tag}"})
        cls.coffee.write({"available_in_pos": True,
                          "pos_categ_ids": [Command.set(cls.drinks.ids)]})

    def _limit(self, partner, limit, policy="block"):
        return self.env["staff.allowance.rule"].create({
            "partner_id": partner.id, "pos_category_id": self.drinks.id,
            "daily_limit": limit, "policy": policy})

    def test_the_app_shows_the_allowance(self):
        partner = self._me()
        self.assertEqual(self._call("/api/v1/allowance")[1], {"has_allowance": False, "limits": []})

        # Before rule: me and summary show no allowance
        me_data = self._call("/api/v1/me")[1]
        self.assertFalse(me_data.get("has_allowance"))
        summary_data = self._call("/api/v1/summary")[1]
        self.assertFalse(summary_data.get("has_allowance"))

        self._limit(partner, 3)
        limits = self._call("/api/v1/allowance")[1]["limits"]
        self.assertEqual([(l["category_id"], l["limit"], l["remaining"], l["at_the_limit"])
                          for l in limits], [(self.drinks.id, 3, 3, "block")])

        # After rule: me and summary reflect the allowance
        me_data = self._call("/api/v1/me")[1]
        self.assertTrue(me_data.get("has_allowance"))
        summary_data = self._call("/api/v1/summary")[1]
        self.assertTrue(summary_data.get("has_allowance"))
        self.assertEqual(summary_data.get("allowance_status"), "none")

        products = {p["id"]: p for p in self._call(
            "/api/v1/products", {"search": self.tag, "limit": 50})[1]["products"]}
        self.assertEqual((products[self.coffee.id]["allowance"]["restricted"],
                          products[self.coffee.id]["allowance"]["remaining"]), (True, 3))
        self.assertEqual(products[self.topup_product.id]["allowance"], {"restricted": False})

    def test_allowance_history(self):
        partner = self._me()
        self._limit(partner, 5)
        # Empty history initially
        status, data = self._call("/api/v1/allowance/history")
        self.assertEqual(status, 200)
        self.assertEqual(data["total"], 0)
        self.assertEqual(data["orders"], [])

        # Checkout 2 items
        self._checkout("account", 2)
        status, data = self._call("/api/v1/allowance/history")
        self.assertEqual(status, 200)
        self.assertEqual(data["total"], 1)
        self.assertEqual(len(data["orders"]), 1)
        self.assertEqual(data["orders"][0]["qty"], 2)
        self.assertEqual(data["orders"][0]["category_id"], self.drinks.id)

    def test_checkout_follows_the_limit_and_counts_app_orders(self):
        partner = self._me()
        rule = self._limit(partner, 2)
        SaleOrder = self.env["sale.order"]

        before = self._orders_of(partner)
        status, data = self._checkout("account", 3)
        self.assertEqual(data["error"], "allowance_limit_reached", data)
        self.assertTrue(data["messages"])
        self.assertEqual(self._orders_of(partner), before, "the refused order is not kept")
        self.assertTrue(self.env["staff.allowance.attempt"].search([
            ("partner_id", "=", partner.id), ("source", "=", "app")]),
            "the refusal is logged in Blocked Attempts")

        status, data = self._checkout("account", 2)
        self.assertEqual(status, 200, data)
        self.assertNotIn("allowance_warnings", data)
        order = SaleOrder.browse(data["order"]["id"])
        self.assertEqual([(e.qty, e.source) for e in order.allowance_order_ids], [(2, "app")])
        self.assertEqual(self._call("/api/v1/allowance")[1]["limits"][0]["remaining"], 0)

        rule.policy = "allow"
        status, data = self._checkout("account", 1)
        self.assertEqual(status, 200, data)
        self.assertTrue(data.get("allowance_warnings"), "allowed, with a warning to show")
        self.assertTrue(SaleOrder.browse(data["order"]["id"]).allowance_order_ids.is_over_limit)

        order._action_cancel()
        self.assertFalse(order.allowance_order_ids, "cancelling an order gives the allowance back")

    def test_menu_shows_allowance(self):
        partner = self._me()
        self._limit(partner, 3)
        self._card(partner, 40)
        status, data = self._call("/api/v1/menu", {"search": self.tag})
        self.assertEqual(status, 200, data)
        self.assertTrue(data["customer"]["has_allowance"])
        self.assertEqual(data["customer"]["wallet_balance"], 40)
        limits = data["customer"]["allowance"]["limits"]
        self.assertEqual([(l["category_id"], l["limit"], l["remaining"]) for l in limits],
                         [(self.drinks.id, 3, 3)])
        # Check product allowance
        coffee = next(p for p in data["products"] if p["id"] == self.coffee.id)
        self.assertTrue(coffee["allowance"]["restricted"])
        self.assertEqual(coffee["allowance"]["remaining"], 3)

