{
    "name": "Staff Allowance",
    "version": "19.0.6.3.0",
    "category": "Human Resources",
    "summary": "Daily POS-category limits per contact (staff through their work "
               "contact) — free by default, capped only where you say so",
    "description": """
Staff Allowance
===============

Cap how much of a **POS category** a person may take per day. Built on the
POS categories you already use, so the limits follow your real product data.

Nothing is restricted until you add a rule. A rule names one contact and one
POS category; everyone else, and every other category, is untouched. Staff
are managed through their work contact, the same contact the POS sells to.

Limits reset by themselves at each person's local midnight, because
consumption is derived from that day's order records — no counter, no cron.
""",
    "author": "",
    "website": "",
    "license": "LGPL-3",
    "depends": ["hr", "point_of_sale"],
    "data": [
        "security/ir.model.access.csv",
        "security/staff_allowance_security.xml",
        "data/ir_sequence_data.xml",
        "views/staff_allowance_rule_views.xml",
        "views/staff_allowance_plan_views.xml",
        "views/staff_allowance_order_views.xml",
        "views/staff_allowance_usage_views.xml",
        "views/staff_allowance_attempt_views.xml",
        "views/hr_employee_views.xml",
        "views/res_partner_views.xml",
        "views/pos_order_views.xml",
        "views/staff_allowance_give_views.xml",
        "views/allowance_people_views.xml",
        "views/staff_allowance_menus.xml",
    ],
    # Cashier warning on the POS payment screen. Recording works without it.
    "assets": {
        "point_of_sale._assets_pos": [
            "staff_allowance/static/src/js/pos_allowance_warning.js",
        ],
    },
    "installable": True,
    "application": True,
    "auto_install": False,
}
