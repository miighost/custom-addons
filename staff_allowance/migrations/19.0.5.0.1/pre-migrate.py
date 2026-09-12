"""Clear duplicated daily usage rows so the new unique index can be created.

Until this version uniqueness was only a Python check, which two simultaneous
orders could both pass. The table is a projection of the orders, so the
duplicated days are dropped here and rebuilt in post-migrate.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("""
        DELETE FROM staff_allowance_usage u
         USING (
            SELECT COALESCE(employee_id, 0) AS employee_id,
                   COALESCE(partner_id, 0) AS partner_id,
                   pos_category_id, day
              FROM staff_allowance_usage
             GROUP BY 1, 2, 3, 4
            HAVING count(*) > 1
         ) dup
         WHERE COALESCE(u.employee_id, 0) = dup.employee_id
           AND COALESCE(u.partner_id, 0) = dup.partner_id
           AND u.pos_category_id = dup.pos_category_id
           AND u.day = dup.day
    """)
    if cr.rowcount:
        _logger.info("Dropped %s duplicated daily usage rows; post-migrate "
                     "rebuilds them.", cr.rowcount)
