"""Remove allowance entries earlier versions recorded for unpaid POS tickets.

The ticket is recorded again once it is paid. The daily usage rows that
pre-migrate dropped are rebuilt by the 19.0.6.0.0 post-migrate, which runs
after this one.
"""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env["pos.order"].search([
        ("allowance_recorded", "=", True),
        ("state", "not in", ("paid", "done")),
    ])._record_allowance()
