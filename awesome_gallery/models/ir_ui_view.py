# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import ValidationError


class View(models.Model):
    _inherit = "ir.ui.view"

    type = fields.Selection(selection_add=[("gallery", "Awesome Gallery")])

    def _get_view_info(self):
        return {"gallery": {"icon": "oi oi-view-list"}} | super()._get_view_info()

    def _validate_tag_gallery(self, node, name_manager, node_info):
        if not node_info["validate"]:
            return
        image_field = node.get("image_field")
        tooltip_field = node.get("tooltip_field")
        if image_field:
            name_manager.has_field(node, image_field.split(".", 1)[0], node_info)
        if tooltip_field:
            name_manager.has_field(node, tooltip_field.split(".", 1)[0], node_info)
        for child in node:
            if child.tag == "field":
                name_manager.has_field(node, child.get("name"), node_info)
