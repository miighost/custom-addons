"""End-to-end tests of the allowance API (/api/allowance/*), over real HTTP.

These routes use an Odoo login session (auth="user").

    odoo -d YOUR_DB -u staff_allowance --test-tags /staff_allowance --stop-after-init
"""
import uuid

from odoo import Command
from odoo.tests import HttpCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestAllowanceApi(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        tag = uuid.uuid4().hex[:6]
        cls.login = f"allowance-api-{tag}"
        cls.user = new_test_user(cls.env, login=cls.login, password=cls.login,
                                 groups="base.group_user")
        cls.partner = cls.user.partner_id
        Category = cls.env["pos.category"]
        cls.coffee = Category.create({"name": f"Coffee {tag}"})
        cls.tea = Category.create({"name": f"Tea {tag}"})
        cls.espresso = cls.env["product.product"].create({
            "name": f"Espresso {tag}", "available_in_pos": True,
            "pos_categ_ids": [Command.set(cls.coffee.ids)], "taxes_id": [Command.clear()]})
        cls.env["staff.allowance.rule"].create({
            "partner_id": cls.partner.id, "pos_category_id": cls.coffee.id,
            "daily_limit": 2, "policy": "approval"})

    def setUp(self):
        super().setUp()
        self.authenticate(self.login, self.login)

    def _get(self, route, **params):
        response = self.url_open(route, params=params)
        return response.status_code, response.json()

    def _post(self, route, body):
        response = self.url_open(route, json=body, method="POST")
        return response.status_code, response.json()

    def test_rules_and_quota(self):
        status, data = self._get("/api/allowance/rules")
        self.assertEqual(status, 200, data)
        self.assertEqual(data["beneficiary"]["id"], self.partner.id)
        self.assertEqual([(r["category_id"], r["limit"], r["remaining"]) for r in data["rules"]],
                         [(self.coffee.id, 2, 2)])

        status, data = self._get("/api/allowance/quota", product_id=self.espresso.id)
        self.assertEqual((data["category_id"], data["restricted"], data["limit"]),
                         (self.coffee.id, True, 2))

        status, data = self._get("/api/allowance/quota", category_id=self.tea.id)
        self.assertEqual((data["restricted"], data["limit"], data["remaining"]), (False, None, None))

        status, data = self._get("/api/allowance/quota", category_id="abc")
        self.assertEqual((status, data["error"]), (400, "bad_request"))

    def test_order_approval_cancel_and_history(self):
        status, data = self._post("/api/allowance/order", {"product_id": self.espresso.id, "qty": 2})
        self.assertEqual(status, 200, data)
        self.assertFalse(data["requires_approval"])
        done_id = data["order"]["id"]
        self.assertEqual(data["quota"]["remaining"], 0)

        status, data = self._post("/api/allowance/order", {"product_id": self.espresso.id, "qty": 1})
        self.assertEqual(status, 200, data)
        self.assertTrue(data["requires_approval"], "over the limit with an approval policy")
        draft_id = data["order"]["id"]
        self.assertEqual(data["order"]["state"], "draft")

        status, data = self._post("/api/allowance/cancel", {"order_id": done_id})
        self.assertEqual((status, data["error"]), (409, "not_cancellable"))
        status, data = self._post("/api/allowance/cancel", {"order_id": draft_id})
        self.assertEqual(status, 200, data)

        status, data = self._post("/api/allowance/order", {"category_id": self.tea.id, "qty": 1})
        self.assertEqual(status, 200, data)
        self.assertIsNone(data["order"], "no rule for tea: allowed and not tracked")

        status, data = self._get("/api/allowance/history")
        self.assertEqual([o["id"] for o in data["orders"]], [done_id])
