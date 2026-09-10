# -*- coding: utf-8 -*-
#################################################################################
# Author      : Zero For Information Systems (<www.erpzero.com>)
# Copyright(c): 2016-Zero For Information Systems
# All Rights Reserved.
#Zerosystems #odoo #erp
# This program is copyright property of the author mentioned above.
# You can`t redistribute it and/or modify it.
#
#################################################################################
{
    'name': 'Create Bill from Purchase Order',
    'version': '9.0.1',
    'category': 'Purchase',
    "author": 'Zero Systems',
    "company": 'Zero for Information Systems',
    "website": "https://www.erpzero.com",
    "email": "sales@erpzero.com",
    "sequence": 0,
    'summary': """Create bill from Purchase Order """,
    'description': """
        from odoo19 Create Bill Button removed from Purchase Order form but this module added it like odoo18
        """,
    'depends': [
        'purchase',
    ],
    'data': [
        'views/purchase.xml',
    ],
    'demo': [
    ],
    'license': 'OPL-1',
    'live_test_url': 'https://youtu.be/D0mGgFSDgI4',
    'images': ['static/description/bill.png'],
    'installable': True,
    'auto_install': False,
    'application': False,
    'price': 00.00,
    'pre_init_hook': 'pre_init_check',
    'currency': 'EUR',
}
