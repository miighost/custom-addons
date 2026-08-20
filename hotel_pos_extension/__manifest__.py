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
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU LESSER GENERAL PUBLIC LICENSE (LGPL v3) for more details.
#
#    You should have received a copy of the GNU LESSER GENERAL PUBLIC LICENSE
#    (LGPL v3) along with this program.
#    If not, see <http://www.gnu.org/licenses/>.
#
#############################################################################
{
    'name': 'Hotel POS Extension',
    'version': '19.0.1.0.0',
    'category': 'Point of Sale',
    'summary': 'Hotel Room Charge from POS',
    'description': """This module allows charging POS orders directly to hotel folios.""",
    'author': 'MiiG Solution',
    'company': 'MiiG Solution',
    'maintainer': 'MiiG Solution',
    'website': 'https://www.miigsolution.so',
    'depends': ['point_of_sale', 'hotel_management_odoo'],
    'data': [
        'security/ir.model.access.csv',
        'data/pos_payment_method_data.xml',
        'views/pos_payment_method_views.xml',
        'views/pos_order_views.xml',
        'views/room_booking_views.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'hotel_pos_extension/static/src/app/screens/payment_screen/HotelPaymentScreen.js',
            'hotel_pos_extension/static/src/overrides/models/HotelPosOrder.js',
            'hotel_pos_extension/static/src/app/screens/product_screen/HotelRoomSelectionButton.js',
            'hotel_pos_extension/static/src/js/**/*',
            'hotel_pos_extension/static/src/xml/**/*',
        ],
    },
    'license': 'LGPL-3',
    'installable': True,
    'auto_install': False,
    'post_init_hook': 'post_init_hook',
    'uninstall_hook': 'uninstall_hook',
    'images': ['static/description/banner.jpg'],
    'application': False,
}
