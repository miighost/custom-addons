"""Repair data written by earlier versions.

1. Earlier versions recorded POS tickets while they were still unpaid. Those
   entries are removed; the ticket is recorded again once it is paid.
2. Rebuild the daily usage rows that pre-migrate dropped.
"""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    env["pos.order"].search([
        ("allowance_recorded", "=", True),
        ("state", "not in", ("paid", "done")),
    ])._record_allowance()

    cr.execute("""
        SELECT DISTINCT o.employee_id, o.partner_id, o.pos_category_id, o.order_date
          FROM staff_allowance_order o
         WHERE o.state IN ('draft', 'done')
           AND o.order_date IS NOT NULL
           AND NOT EXISTS (
               SELECT 1
                 FROM staff_allowance_usage u
                WHERE COALESCE(u.employee_id, 0) = COALESCE(o.employee_id, 0)
                  AND COALESCE(u.partner_id, 0) = COALESCE(o.partner_id, 0)
                  AND u.pos_category_id = o.pos_category_id
                  AND u.day = o.order_date)
    """)
    keys = {
        ("hr.employee", employee_id, category_id, day) if employee_id
        else ("res.partner", partner_id, category_id, day)
        for employee_id, partner_id, category_id, day in cr.fetchall()
    }
    env["staff.allowance.usage"]._refresh_keys(keys)
