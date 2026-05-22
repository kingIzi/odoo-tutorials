from odoo import api, fields, models
from odoo.exceptions import ValidationError


class EstatePropertyOffer(models.Model):
    _name = "estate.property.offer"
    _description = "Real Estate Property Offer"
    _order = "price desc"

    price = fields.Float(required=True)
    status = fields.Selection(
        [
            ("pending", "Pending"),
            ("accepted", "Accepted"),
            ("refused", "Refused"),
        ],
        default="refused",
        required=True,
        copy=False,
    )
    property_id = fields.Many2one("estate.property", required=True)
    partner_id = fields.Many2one("res.partner", required=True)

    @api.constrains("price")
    def _check_price(self):
        for record in self:
            if record.price <= 0:
                raise ValidationError("The price must be greater than 0.")

    def offer_confirmed(self):
        for record in self:
            record.status = "accepted"
            record.property_id.buyer = record.partner_id
        return True

    def offer_rejected(self):
        for record in self:
            record.status = "refused"
            record.property_id.buyer = record.partner_id
        return True
