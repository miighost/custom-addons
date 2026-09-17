"""Move employee-based allowances onto the employee's work contact.

From this version an allowance belongs to a contact only. An employee's rules,
orders and blocked attempts move to their work contact -- the contact the POS
sells to and the one Odoo links to their user -- and their plan moves too when
the contact has none.

Where the contact already had its own rule for a category, the contact's rule
wins: it is the one the POS was already applying. Daily usage rows of everyone
affected are dropped here and rebuilt from the orders in post-migrate.
"""
import logging

_logger = logging.getLogger(__name__)

# Each employee's contact: the work contact, else the linked user's contact.
CONTACT = """
    SELECT e.id AS employee_id,
           COALESCE(e.work_contact_id, u.partner_id) AS partner_id
      FROM hr_employee e
      LEFT JOIN res_users u ON u.id = e.user_id
"""


def _run(cr, query, message, level=logging.INFO):
    cr.execute(query)
    if cr.rowcount:
        _logger.log(level, message, cr.rowcount)


def migrate(cr, version):
    cr.execute("DROP INDEX IF EXISTS staff_allowance_usage_beneficiary_day_unique")

    _run(cr, f"""
        WITH contact AS ({CONTACT})
        DELETE FROM staff_allowance_usage
         WHERE employee_id IS NOT NULL
            OR partner_id IN (
                SELECT c.partner_id FROM contact c
                 WHERE EXISTS (SELECT 1 FROM staff_allowance_rule r
                                WHERE r.employee_id = c.employee_id)
                    OR EXISTS (SELECT 1 FROM staff_allowance_order o
                                WHERE o.employee_id = c.employee_id)
                    OR EXISTS (SELECT 1 FROM hr_employee e
                                WHERE e.id = c.employee_id
                                  AND e.allowance_plan_id IS NOT NULL))
    """, "Dropped %s daily usage rows; post-migrate rebuilds them per contact.")

    _run(cr, f"""
        WITH contact AS ({CONTACT})
        UPDATE res_partner p
           SET allowance_plan_id = e.allowance_plan_id
          FROM hr_employee e
          JOIN contact c ON c.employee_id = e.id
         WHERE p.id = c.partner_id
           AND e.allowance_plan_id IS NOT NULL
           AND p.allowance_plan_id IS NULL
    """, "Moved the allowance plan of %s employees onto their contact.")
    cr.execute(f"""
        WITH contact AS ({CONTACT})
        SELECT count(*)
          FROM hr_employee e
          JOIN contact c ON c.employee_id = e.id
          JOIN res_partner p ON p.id = c.partner_id
         WHERE e.allowance_plan_id IS NOT NULL
           AND p.allowance_plan_id <> e.allowance_plan_id
    """)
    conflicts = cr.fetchone()[0]
    if conflicts:
        _logger.warning("%s employees had a different allowance plan than their "
                        "contact; the contact's plan was kept.", conflicts)

    # A contact keeps its own rule for a category. Among several employee
    # rules landing on the same contact and category, the oldest is kept.
    _run(cr, f"""
        WITH contact AS ({CONTACT}),
        mapped AS (
            SELECT r.id, c.partner_id, r.pos_category_id,
                   row_number() OVER (PARTITION BY c.partner_id, r.pos_category_id
                                      ORDER BY r.id) AS n
              FROM staff_allowance_rule r
              JOIN contact c ON c.employee_id = r.employee_id
        )
        DELETE FROM staff_allowance_rule r
         USING mapped m
         WHERE r.id = m.id
           AND (m.partner_id IS NULL
                OR m.n > 1
                OR EXISTS (SELECT 1 FROM staff_allowance_rule k
                            WHERE k.employee_id IS NULL
                              AND k.partner_id = m.partner_id
                              AND k.pos_category_id = m.pos_category_id))
    """, "Dropped %s employee allowance rules: their contact already had a rule "
         "for the same category, which was kept.", logging.WARNING)

    for table, label in (("staff_allowance_rule", "rules"),
                         ("staff_allowance_order", "orders"),
                         ("staff_allowance_attempt", "blocked attempts")):
        _run(cr, f"""
            WITH contact AS ({CONTACT})
            UPDATE {table} t
               SET partner_id = c.partner_id, employee_id = NULL
              FROM contact c
             WHERE t.employee_id = c.employee_id
               AND c.partner_id IS NOT NULL
        """, f"Moved %s allowance {label} from employees to their contact.")
        # Only possible for an employee with neither a work contact nor a user.
        _run(cr, f"DELETE FROM {table} WHERE employee_id IS NOT NULL",
             f"Deleted %s allowance {label} of employees with no contact at all.",
             logging.WARNING)
