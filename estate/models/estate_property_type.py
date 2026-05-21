from odoo import fields, models


class EstatePropertyType(models.Model):
    _name = "estate.property.type"
    _description = "Real Estate Property Type"
    _order = "id"

    name = fields.Char(required=True)

    _check_name = models.Constraint(
        "Unique(name)", "Property type name must be unique."
    )
