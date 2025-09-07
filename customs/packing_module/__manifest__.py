{
    'name': 'Packing Module',
    'version': '18.0.1.0.0',
    'category': 'Warehouse',
    'depends': ['base', 'website'],
    'data': [
        'security/ir.model.access.csv',
        'views/packing_views.xml',
        'views/website_pages.xml',
        'data/packing_data.xml',
    ],
    'installable': True,
    'application': True,
}
