# -- coding: utf-8 --

##############################################################################
#                                                                            #
# Part of WebbyCrown Solutions (Website: www.webbycrown.com).                #
# Copyright © 2025 WebbyCrown Solutions. All Rights Reserved.                #
#                                                                            #
##############################################################################

{
    'name': 'Mama Pharmacy',
    'version': '20.0.2.0.0',
    'summary': 'Multi-branch pharmacy: drug catalog, stock alerts, prescriptions and Point of Sale',
    'author': 'Webbycrown Solutions',
    'website': 'www.webbycrown.com',
    'category': 'Industries/Healthcare',
    'license': 'LGPL-3',
    'depends': [
        'base', 'mail', 'web', 'contacts', 'product', 'stock', 'stock_account',
        'uom', 'point_of_sale', 'pos_stock', 'account',
    ],
    'data': [
        'security/pharmacy_security.xml',
        'security/ir.access.csv',
        'data/sequences.xml',
        'views/patient_views.xml',
        'views/doctor_prescriber_views.xml',
        'views/drug_views.xml',
        'views/pharmacy_views.xml',
        'views/prescription_views.xml',
        'views/availability_views.xml',
        'views/reporting_views.xml',
        'views/menu.xml',
        'data/demo.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'pharmacy_management_system/static/src/scss/pharma_kanban.scss',
        ],
    },
    'images': ['static/description/main_screenshot.png'],
    'icon': 'static/description/icon.png',
    'application': True,
    'installable': True,
}
