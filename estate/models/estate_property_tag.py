from odoo import fields, models


class EstateProperty(models.Model):
    _name = "estate.property.tag"
    _description = "Real Estate Property Tag"
    _order = "id"

    name = fields.Char(required=True)
