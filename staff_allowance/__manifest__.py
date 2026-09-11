{
    "name": "Staff Allowance",
    "version": "19.0.2.2.0",
    "category": "Human Resources",
    "summary": "Daily per-category allowances for employees and contacts, with "
               "plans, over-limit handling and a REST API for mobile apps",
    "description": """
Staff Allowance
===============

Give employees **and contacts** a daily quota per category (Coffee 10/day,
Snacks 5/day...). The quota resets by itself at each person's local midnight,
because consumption is derived from the day's order records -- no counter to
reset, no cron job to fail.

Limits cascade, most specific first:

1. a personal line in the Allowance tab
2. the allowance plan (tier) assigned to the person
3. the category default

When someone reaches their limit, the category decides what happens: block the
order with a clear message, allow it but require approval, or allow and flag it.
Blocked attempts are logged so you can see who ran out.
""",
    "author": "",
    "website": "",
    "license": "LGPL-3",
    "depends": ["hr", "product", "mail"],
    "data": [
        "security/ir.model.access.csv",
        "security/staff_allowance_security.xml",
        "data/ir_sequence_data.xml",
        "views/staff_allowance_category_views.xml",
        "views/staff_allowance_plan_views.xml",
        "views/staff_allowance_line_views.xml",
        "views/staff_allowance_order_views.xml",
        "views/staff_allowance_usage_views.xml",
        "views/staff_allowance_attempt_views.xml",
        "views/hr_employee_views.xml",
        "views/res_partner_views.xml",
        "views/staff_allowance_menus.xml",
        "data/staff_allowance_data.xml",
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
}
