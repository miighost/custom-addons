import json
import logging

from odoo import _, http
from odoo.exceptions import AccessError, ValidationError
from odoo.http import request

_logger = logging.getLogger(__name__)


class StaffAllowanceController(http.Controller):
    """Plain-JSON endpoints (type='http'), no JSON-RPC envelope.

    All the decision logic lives in `staff.allowance.category._place_order()`,
    so the app, the backend and any other caller behave identically. This
    controller only translates HTTP to that call.

    AUTH: routes are auth='user'. If your own API module resolves the caller
    from a token, do it in `_beneficiary()` below and switch to auth='public'.
    """

    # ------------------------------------------------------------------
    # Plumbing
    # ------------------------------------------------------------------
    def _json(self, payload, status=200):
        return request.make_json_response(payload, status=status)

    def _error(self, code, message, status=400, extra=None):
        payload = {"success": False, "error": code, "message": message}
        if extra:
            payload.update(extra)
        return self._json(payload, status=status)

    def _body(self):
        try:
            raw = request.httprequest.get_data(as_text=True)
            return json.loads(raw) if raw else {}
        except ValueError:
            return {}

    def _beneficiary(self):
        """The employee or contact behind the current request.

        Employee first (staff perks), falling back to the user's own contact
        so the same endpoints serve customer-facing allowances.
        """
        user = request.env.user
        employee = request.env["hr.employee"].sudo().search(
            [("user_id", "=", user.id)], limit=1
        )
        return employee or user.partner_id

    def _category(self, code):
        return request.env["staff.allowance.category"].sudo().search(
            [("code", "=", code)], limit=1
        )

    def _quota_payload(self, category, beneficiary):
        data = category._evaluate(beneficiary, increment=0)
        for key in ("ok", "reason", "message", "requires_approval"):
            data.pop(key, None)
        return data

    # ------------------------------------------------------------------
    # GET /api/allowance/categories
    # ------------------------------------------------------------------
    @http.route("/api/allowance/categories", type="http", auth="user",
                methods=["GET"], csrf=False)
    def allowance_categories(self, **kw):
        beneficiary = self._beneficiary()
        if not beneficiary:
            return self._error("no_beneficiary",
                               _("No employee or contact is linked to this user."),
                               404)
        Category = request.env["staff.allowance.category"].sudo()
        payload = []
        for category in Category.search([]):
            data = self._quota_payload(category, beneficiary)
            if data["allowed"]:
                data["products"] = [
                    {"id": p.id, "name": p.display_name}
                    for p in category.product_ids
                ]
                payload.append(data)
        return self._json({
            "success": True,
            "beneficiary": {
                "type": "employee" if beneficiary._name == "hr.employee"
                        else "partner",
                "id": beneficiary.id,
                "name": beneficiary.display_name,
            },
            "categories": payload,
        })

    # ------------------------------------------------------------------
    # GET /api/allowance/quota?code=coffee
    # ------------------------------------------------------------------
    @http.route("/api/allowance/quota", type="http", auth="user",
                methods=["GET"], csrf=False)
    def allowance_quota(self, code=None, **kw):
        beneficiary = self._beneficiary()
        if not beneficiary:
            return self._error("no_beneficiary",
                               _("No employee or contact is linked to this user."),
                               404)
        if not code:
            return self._error("missing_code", _("A category code is required."))
        category = self._category(code)
        if not category:
            return self._error("unknown_category",
                               _("Unknown category: %s") % code, 404)
        return self._json({"success": True,
                           **self._quota_payload(category, beneficiary)})

    # ------------------------------------------------------------------
    # POST /api/allowance/order  {"code":"coffee","product_id":5,"qty":1}
    # ------------------------------------------------------------------
    @http.route("/api/allowance/order", type="http", auth="user",
                methods=["POST"], csrf=False)
    def allowance_order(self, **kw):
        body = self._body() or kw
        beneficiary = self._beneficiary()
        if not beneficiary:
            return self._error("no_beneficiary",
                               _("No employee or contact is linked to this user."),
                               404)

        code = body.get("code") or body.get("category_code")
        if not code:
            return self._error("missing_code", _("A category code is required."))
        category = self._category(code)
        if not category:
            return self._error("unknown_category",
                               _("Unknown category: %s") % code, 404)

        try:
            qty = int(body.get("qty", 1))
        except (TypeError, ValueError):
            return self._error("bad_qty", _("Quantity must be a whole number."))

        product = request.env["product.product"].sudo().browse(
            int(body.get("product_id") or 0)
        ).exists()

        try:
            result = category._place_order(
                beneficiary, qty=qty, product=product or None,
                source="app", note=body.get("note"),
            )
        except ValidationError as exc:
            return self._error("limit_reached",
                               exc.args[0] if exc.args else str(exc), 429)
        except AccessError as exc:
            return self._error("forbidden", str(exc), 403)
        except Exception:  # never leak a traceback to the app
            _logger.exception("Allowance order failed")
            return self._error("server_error",
                               _("Could not register the order."), 500)

        quota = {k: result[k] for k in
                 ("code", "name", "unlimited", "limit", "used", "remaining",
                  "over_limit", "overdraft", "resets_at", "count_mode", "day",
                  "origin")}

        if not result["ok"]:
            # 429 reads correctly for a quota that is used up; the app can
            # branch on `error` rather than the status code.
            status = 429 if result["reason"] in (
                "limit_reached", "overdraft_exceeded") else 400
            return self._error(result["reason"], result["message"], status,
                               extra={"quota": quota})

        return self._json({
            "success": True,
            "order": result["order"]._to_json(),
            "requires_approval": result["requires_approval"],
            "quota": quota,
        })

    # ------------------------------------------------------------------
    # POST /api/allowance/cancel  {"order_id": 42}
    # ------------------------------------------------------------------
    @http.route("/api/allowance/cancel", type="http", auth="user",
                methods=["POST"], csrf=False)
    def allowance_cancel(self, **kw):
        body = self._body() or kw
        beneficiary = self._beneficiary()
        order = request.env["staff.allowance.order"].sudo().browse(
            int(body.get("order_id") or 0)
        ).exists()
        if not order or order._beneficiary() != beneficiary:
            return self._error("not_found", _("Order not found."), 404)
        order.action_cancel()
        return self._json({
            "success": True,
            "quota": self._quota_payload(order.category_id, beneficiary),
        })

    # ------------------------------------------------------------------
    # GET /api/allowance/history?date_from=&date_to=&code=&limit=
    # ------------------------------------------------------------------
    @http.route("/api/allowance/history", type="http", auth="user",
                methods=["GET"], csrf=False)
    def allowance_history(self, date_from=None, date_to=None, code=None,
                          limit=100, **kw):
        beneficiary = self._beneficiary()
        if not beneficiary:
            return self._error("no_beneficiary",
                               _("No employee or contact is linked to this user."),
                               404)
        Order = request.env["staff.allowance.order"].sudo()
        domain = Order._beneficiary_domain(beneficiary) + [
            ("state", "in", ("draft", "done"))
        ]
        if date_from:
            domain.append(("order_date", ">=", date_from))
        if date_to:
            domain.append(("order_date", "<=", date_to))
        if code:
            domain.append(("category_id.code", "=", code))
        orders = Order.search(domain, limit=min(int(limit), 500))
        return self._json({
            "success": True,
            "count": len(orders),
            "orders": [o._to_json() for o in orders],
        })
