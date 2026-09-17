"""The dashboard is now one regular record instead of throw-away transient ones.

Clear the rows the transient version left behind; the data file creates the
single record the menu opens.
"""


def migrate(cr, version):
    cr.execute("SELECT to_regclass('app_dashboard')")
    if cr.fetchone()[0]:
        cr.execute("DELETE FROM app_dashboard")
