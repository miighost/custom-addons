{
    'name': 'App API (Firebase)',
    'version': '19.0.1.0.0',
    'summary': 'REST endpoints for a FlutterFlow client app authenticated with Firebase',
    'author': 'QBH',
    'license': 'LGPL-3',
    'depends': ['base', 'sale_management', 'loyalty'],
    'data': [
        'data/ir_config_parameter.xml',
        'views/res_partner_views.xml',
    ],
    'external_dependencies': {'python': ['jwt', 'cryptography']},
    'installable': True,
    'application': False,
}
