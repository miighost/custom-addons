"""Finish moving allowances onto contacts: refresh names, rebuild daily usage."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    for model in ("staff.allowance.rule", "staff.allowance.order",
                  "staff.allowance.attempt"):
        records = env[model].with_context(active_test=False).search([])
        env.add_to_compute(records._fields["beneficiary_name"], records)
    env.flush_all()

    cr.execute("""
        SELECT DISTINCT o.partner_id, o.pos_category_id, o.order_date
          FROM staff_allowance_order o
         WHERE o.state IN ('draft', 'done')
           AND o.order_date IS NOT NULL
           AND NOT EXISTS (
               SELECT 1
                 FROM staff_allowance_usage u
                WHERE u.partner_id = o.partner_id
                  AND u.pos_category_id = o.pos_category_id
                  AND u.day = o.order_date)
    """)
    env["staff.allowance.usage"]._refresh_keys(cr.fetchall())
