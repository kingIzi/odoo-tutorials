{
    "name": "Strat",
    "version": "19.0.1.0.0",
    "summary": "AI Chat Assistant",
    "description": "A floating chat interface for Odoo",
    "author": "Training",
    "license": "LGPL-3",
    "application": True,
    "category": "Tools",
    "depends": ["web"],
    "data": [
        "security/ir.model.access.csv",
        "views/strat_link_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "strat/static/src/css/strat_chat.css",
            "strat/static/src/components/strat_chat.xml",
            "strat/static/src/components/strat_chat.js",
        ],
    },
}
