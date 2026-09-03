{
    'name': 'App API (Firebase)',
    'version': '19.0.1.0.0',
    'category': 'Sales/Sales',
    'summary': 'REST endpoints for a FlutterFlow client app authenticated with Firebase',
    'author': 'QBH',
    'license': 'LGPL-3',
    'depends': ['base', 'sale_management', 'loyalty', 'sale_loyalty'],
    'data': [
        'data/ir_config_parameter.xml',
        'views/res_partner_views.xml',
        'views/product_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'installable': True,
    'application': True,
}
