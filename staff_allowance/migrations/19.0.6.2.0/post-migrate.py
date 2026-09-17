"""Daily usage rows now list the products taken ("Espresso ×2, Latte ×1").

Rebuild every row so the existing ones get it too.
"""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env["staff.allowance.usage"].action_rebuild()
