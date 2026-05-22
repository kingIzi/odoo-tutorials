from odoo import fields, models


class EstateProperty(models.Model):
    _name = "estate.property.tag"
    _description = "Real Estate Property Tag"
    _order = "name"

    name = fields.Char(required=True)
    color = fields.Integer()

    _check_name = models.Constraint("Unique(name)", "Property tag name must be unique.")
