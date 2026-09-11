import json
import logging

from odoo import _, http
from odoo.exceptions import AccessError, ValidationError
from odoo.http import request

_logger = logging.getLogger(__name__)

QUOTA_KEYS = ("category_id", "category_name", "restricted", "origin", "limit",
              "used", "remaining", "count_mode", "policy", "over_limit",
              "overdraft", "resets_at", "day")


class StaffAllowanceController(http.Controller):
    """Plain-JSON endpoints (type='http'), no JSON-RPC envelope.

    All decisions go through staff.allowance.rule._place_order(), so the app,
    the backend and the POS behave identically.

    AUTH: routes are auth='user'. If your own API module resolves the caller
    from a token, do it in _beneficiary() and switch to auth='public'.
    """

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
        user = request.env.user
        employee = request.env["hr.employee"].sudo().search(
            [("user_id", "=", user.id)], limit=1)
        return employee or user.partner_id

    def _quota(self, evaluation):
        return {k: evaluation[k] for k in QUOTA_KEYS}

    # ------------------------------------------------------------------
    # GET /api/allowance/rules
    # Only the categories this person is capped in. Everything else is free.
    # ------------------------------------------------------------------
    @http.route("/api/allowance/rules", type="http", auth="user",
                methods=["GET"], csrf=False)
    def allowance_rules(self, **kw):
        beneficiary = self._beneficiary()
        if not beneficiary:
            return self._error("no_beneficiary",
                               _("No employee or contact is linked to this user."),
                               404)
        Rule = request.env["staff.allowance.rule"].sudo()
        categories = Rule.search(
            Rule._beneficiary_domain(beneficiary)).mapped("pos_category_id")
        plan = beneficiary.allowance_plan_id
        if plan:
            categories |= plan.line_ids.mapped("pos_category_id")
        return self._json({
            "success": True,
            "beneficiary": {
                "type": "employee" if beneficiary._name == "hr.employee"
                        else "partner",
                "id": beneficiary.id,
                "name": beneficiary.display_name,
            },
            "default_is_free": True,
            "rules": [self._quota(Rule._evaluate(beneficiary, category))
                      for category in categories],
        })

    # ------------------------------------------------------------------
    # GET /api/allowance/quota?category_id=5   (or ?product_id=12)
    # ------------------------------------------------------------------
    @http.route("/api/allowance/quota", type="http", auth="user",
                methods=["GET"], csrf=False)
    def allowance_quota(self, category_id=None, product_id=None, **kw):
        beneficiary = self._beneficiary()
        if not beneficiary:
            return self._error("no_beneficiary",
                               _("No employee or contact is linked to this user."),
                               404)
        Rule = request.env["staff.allowance.rule"].sudo()
        category = self._resolve_category(category_id, product_id)
        if not category:
            return self._error("missing_category",
                               _("Provide a category_id or a product_id."))
        return self._json({"success": True,
                           **self._quota(Rule._evaluate(beneficiary, category))})

    def _resolve_category(self, category_id, product_id):
        if category_id:
            return request.env["pos.category"].sudo().browse(
                int(category_id)).exists()
        if product_id:
            product = request.env["product.product"].sudo().browse(
                int(product_id)).exists()
            return request.env["staff.allowance.rule"]._category_of_product(product)
        return request.env["pos.category"]

    # ------------------------------------------------------------------
    # POST /api/allowance/order  {"product_id": 12, "qty": 1}
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

        try:
            qty = int(body.get("qty", 1))
        except (TypeError, ValueError):
            return self._error("bad_qty", _("Quantity must be a whole number."))

        product = request.env["product.product"].sudo().browse(
            int(body.get("product_id") or 0)).exists()
        category = self._resolve_category(body.get("category_id"),
                                          body.get("product_id"))
        if not category:
            return self._error(
                "missing_category",
                _("Provide a category_id, or a product that belongs to a POS "
                  "category."))

        try:
            result = request.env["staff.allowance.rule"].sudo()._place_order(
                beneficiary, pos_category=category, product=product or None,
                qty=qty, source="app", note=body.get("note"))
        except ValidationError as exc:
            return self._error("limit_reached",
                               exc.args[0] if exc.args else str(exc), 429)
        except AccessError as exc:
            return self._error("forbidden", str(exc), 403)
        except Exception:  # never leak a traceback to the app
            _logger.exception("Allowance order failed")
            return self._error("server_error",
                               _("Could not register the order."), 500)

        if not result["ok"]:
            status = 429 if result["reason"] in (
                "limit_reached", "tolerance_exceeded") else 400
            return self._error(result["reason"], result["message"], status,
                               extra={"quota": self._quota(result)})

        return self._json({
            "success": True,
            "order": result["order"]._to_json(),
            "requires_approval": result["requires_approval"],
            "quota": self._quota(result),
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
            int(body.get("order_id") or 0)).exists()
        if not order or order._beneficiary() != beneficiary:
            return self._error("not_found", _("Order not found."), 404)
        category = order.pos_category_id
        order.action_cancel()
        return self._json({
            "success": True,
            "quota": self._quota(
                request.env["staff.allowance.rule"].sudo()._evaluate(
                    beneficiary, category)),
        })

    # ------------------------------------------------------------------
    # GET /api/allowance/history?date_from=&date_to=&category_id=&limit=
    # ------------------------------------------------------------------
    @http.route("/api/allowance/history", type="http", auth="user",
                methods=["GET"], csrf=False)
    def allowance_history(self, date_from=None, date_to=None, category_id=None,
                          limit=100, **kw):
        beneficiary = self._beneficiary()
        if not beneficiary:
            return self._error("no_beneficiary",
                               _("No employee or contact is linked to this user."),
                               404)
        Order = request.env["staff.allowance.order"].sudo()
        domain = Order._beneficiary_domain(beneficiary) + [
            ("state", "in", ("draft", "done"))]
        if date_from:
            domain.append(("order_date", ">=", date_from))
        if date_to:
            domain.append(("order_date", "<=", date_to))
        if category_id:
            domain.append(("pos_category_id", "=", int(category_id)))
        orders = Order.search(domain, limit=min(int(limit), 500))
        return self._json({"success": True, "count": len(orders),
                           "orders": [o._to_json() for o in orders]})
