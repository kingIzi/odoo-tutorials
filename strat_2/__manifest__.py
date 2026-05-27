{
    "name": "Strat 2.0",
    "version": "19.0.1.0.0",
    "summary": "AI Chat Assistant v2",
    "description": "A floating chat interface for Odoo (v2)",
    "author": "Training",
    "license": "LGPL-3",
    "application": True,
    "category": "Tools",
    "depends": ["web"],
    "data": [
        "security/ir.model.access.csv",
    ],
    "assets": {
        "web.assets_backend": [
            "strat_2/static/src/css/strat_2_chat.css",
            "strat_2/static/src/components/strat_2_chat.xml",
            "strat_2/static/src/components/strat_2_chat.js",
        ],
    },
}
