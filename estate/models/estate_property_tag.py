from odoo import fields, models


class EstateProperty(models.Model):
    _name = "estate.property.tag"
    _description = "Real Estate Property Tag"
    _order = "id"

    name = fields.Char(required=True)

    _check_name = models.Constraint("Unique(name)", "Property tag name must be unique.")
