# -*- coding: utf-8 -*-
{
    "name": "Gallery View",
    "summary": "Gallery View Tutorial",
    "description": "Gallery View Tutorial",
    "version": "0.1",
    "application": True,
    "category": "Tutorials",
    "installable": True,
    "depends": ["web", "contacts"],
    "data": [
        "views/views.xml",
    ],
    "assets": {
        "web.assets_backend": ["awesome_gallery/static/src/**/*"],
    },
    "author": "Odoo S.A.",
    "license": "AGPL-3",
}
