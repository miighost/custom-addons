"""Only people with a limit are tracked from this version on.

Earlier versions also copied every POS sale of customers without a rule or
plan into the allowance orders. Remove those copies: they are sales to people
who have no limit on that category (no rule, active or archived, and nothing
in their plan). The POS orders themselves are untouched, and orders placed
through the app are kept.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {"active_test": False})
    Order = env["staff.allowance.order"]
    Rule = env["staff.allowance.rule"]

    entries = Order.search([("source", "=", "pos")])
    covered = {}
    for partner in entries.partner_id:
        categories = Rule.search([("partner_id", "=", partner.id)]).pos_category_id
        categories |= partner.allowance_plan_id.line_ids.pos_category_id
        covered[partner.id] = set(categories.ids)

    untracked = entries.filtered(
        lambda order: order.pos_category_id.id not in covered[order.partner_id.id])
    count = len(untracked)
    for start in range(0, count, 1000):
        untracked[start:start + 1000].with_context(active_test=True).unlink()
    if count:
        _logger.info("Removed %s allowance orders copied from POS sales of people "
                     "without a limit on that category.", count)
