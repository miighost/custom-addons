# -*- coding: utf-8 -*-
#############################################################################
#
#    MiiG Solution
#
#    Copyright (C) 2026-TODAY MiiG Solution(<https://www.miigsolution.so>)
#    Author: MiiG Solution(<https://www.miigsolution.so>)
#
#    You can modify it under the terms of the GNU LESSER
#    GENERAL PUBLIC LICENSE (LGPL v3), Version 3.
#
#############################################################################
{
    'name': 'Hotel Banquet & Event Management',
    'version': '19.0.1.0.0',
    'category': 'Sales/Hotel',
    'summary': 'Manage Banquet Quotations, Orders, Halls, Services, Multi-day line calculations, Terms and Invoicing',
    'description': """
Hotel Banquet & Event Management
================================
- Banquet Quotation (QUOT/...) and Banquet Orders (BO/...)
- Customer / Company selection
- Event details: Function Name, Event Type, Date & Time, Pax/Guests, Venue
- Order Lines with 'No of Days' calculating: Qty x No of Days x Unit Price
- Custom Terms and Conditions HTML editor
- Seamless 1-Click Invoicing (INV/...)
- Multi-format PDF Reports (Banquet Quotation, Proforma Invoice, Banquet Contract)
    """,
    'author': 'MiiG Solution',
    'website': 'https://www.miigsolution.so',
    'depends': ['sale_management', 'account'],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'data/banquet_event_type_data.xml',
        'views/banquet_event_type_views.xml',
        'views/banquet_venue_views.xml',
        'views/banquet_order_views.xml',
        'views/account_move_views.xml',
        'views/banquet_customer_statement_views.xml',
        'views/banquet_menus.xml',
        'report/banquet_report.xml',
        'report/banquet_customer_statement_report.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
