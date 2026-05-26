from odoo import Command, models


class EstateProperty(models.Model):
    _inherit = "estate.property"

    def sell_property(self):
        res = super().sell_property()
        for record in self:
            if record.buyer and record.selling_price:
                self.env["account.move"].create(
                    {
                        "partner_id": record.buyer.id,
                        "move_type": "out_invoice",
                        "invoice_line_ids": [
                            Command.create(
                                {
                                    "name": f"{record.name} (6% of selling price)",
                                    "quantity": 1,
                                    "price_unit": record.selling_price * 6 / 100,
                                },
                            ),
                            Command.create(
                                {
                                    "name": "Administrative fees",
                                    "quantity": 1,
                                    "price_unit": 100.00,
                                },
                            ),
                        ],
                    },
                )
        return res
