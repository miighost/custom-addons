# -*- coding: utf-8 -*-
{
    'name': "Odoo Print POS Kitchen Receipt",
    'support': "support@smartronsolutions.co.uk",
    'license': "OPL-1",
    'summary': "Print full kitchen receipts and automatically send POS order changes",
    'description': """
        Print POS Kitchen Receipt by Smartron Solutions.
        Adds kitchen receipt printing actions to the Odoo POS receipt screen and order screen,
        supporting instant KOT printing and automatic delivery of order changes to preparation printers.
    """,
    'author': "Smartron Solutions Pvt Ltd",
    'website': "https://smartronsolutions.co.uk",
    'category': 'Point of Sale',
    'version': '19.0.1.2.0',
    'data': [
        'security/ir.model.access.csv',
        'views/views.xml',
        'views/pos_config_views.xml',
        'wizards/scan_printers_views.xml',
    ],
    'depends': ['base', 'point_of_sale', 'pos_restaurant'],
    'assets': {
        'point_of_sale._assets_pos': [
            'ss_print_pos_kitchen_receipt/static/src/js/utils.js',
            'ss_print_pos_kitchen_receipt/static/src/js/escpos_transport.js',
            'ss_print_pos_kitchen_receipt/static/src/js/ReceiptScreen.js',
            'ss_print_pos_kitchen_receipt/static/src/js/KitchenReceiptComponent.js',
            'ss_print_pos_kitchen_receipt/static/src/js/KotButton.js',
            'ss_print_pos_kitchen_receipt/static/src/xml/ActionpadWidget.xml',
            'ss_print_pos_kitchen_receipt/static/src/xml/ControlButtons.xml',
            'ss_print_pos_kitchen_receipt/static/src/xml/ReceiptScreen.xml',
            'ss_print_pos_kitchen_receipt/static/src/xml/kitchen_receipt/kitchen_receipt.xml',
        ],
    },
    'images': ['static/description/banner.png'],

}
