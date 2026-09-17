{
    'name': 'App API: Staff Allowance',
    'version': '19.0.1.0.0',
    'category': 'Sales/Sales',
    'summary': 'Shows staff allowances in the mobile app and enforces them at checkout',
    'description': """
Connects App API (Firebase) and Staff Allowance. Installed automatically when
both are.

* /api/v1/allowance - the customer's daily limits and what is left today
* every product in /api/v1/products carries an "allowance" block
* /api/v1/checkout follows each rule's "At the Limit" setting, like the POS
* confirmed app orders count against the allowance; cancelling gives it back
""",
    'author': 'QBH',
    'license': 'LGPL-3',
    'depends': ['odoo_app_api', 'staff_allowance'],
    'data': [
        'views/staff_allowance_order_views.xml',
    ],
    'auto_install': True,
    'installable': True,
}
