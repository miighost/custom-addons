# -*- coding: utf-8 -*-
#############################################################################
#
#    MiiG Solution
#
#    Copyright (C) 2026-TODAY MiiG Solution(<https://www.miigsolution.so>)
#    Author: MiiG Solution (<https://www.miigsolution.so>)
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
    "name": "Odoo rest API",
    "version": "19.0.1.0.0",
    "category": "Extra Tools",
    "summary": """This app helps to interact with odoo, backend with help of 
     rest api requests""",
    "description": """The odoo Rest API module allow us to connect to database 
     with the help of GET , POST , PUT and DELETE requests""",
    'author': 'MiiG Solution',
    'company': 'MiiG Solution',
    'maintainer': 'MiiG Solution',
    'website': "https://www.miigsolution.so",
    "depends": ['base', 'web'],
    "data": [
        'security/ir.model.access.csv',
        'views/res_users_views.xml',
        'views/connection_api_views.xml'
    ],
    'images': ['static/description/banner.jpg'],
    'license': 'LGPL-3',
    'installable': True,
    'auto_install': False,
    'application': False,
}
