# -*- coding: utf-8 -*-
{
    "name": "VUE 实现手机端的页面",
    "description": """
        手机端页面的配置实现
    """,
    "author": "静静 (gilbert@osbzr.com)",
    "website": "https://www.odoo.com",
    "category": "Productivity",
    "version": "18.0.1.0.0",
    "depends": ["base", "web"],
    "data": [
        "security/ir.model.access.csv",
        "mobile_model.xml",
    ],
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}
