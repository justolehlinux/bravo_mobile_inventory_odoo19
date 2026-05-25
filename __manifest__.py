{
    'name': 'Bravo Mobile Inventory',
    'version': '19.0.1.0.3',
    'category': 'Inventory/Inventory',
    'summary': 'Fast mobile physical inventory terminal for Bravo Market',
    'description': '''
Mobile-first stock counting page for Odoo 19.
Counts are stored in independent sessions and applied only after preview.
Unknown barcodes can be bound to existing products with controlled access.
''',
    'author': 'Bravo Market',
    'license': 'LGPL-3',
    'depends': ['stock', 'web'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/sequence.xml',
        'views/backend_views.xml',
        'views/templates.xml',
    ],
    'installable': True,
    'application': True,
}
