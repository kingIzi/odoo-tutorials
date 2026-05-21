from odoo import api, fields, models
from odoo.exceptions import ValidationError
from statemachine import State, StateChart

from ..utils.app_utils import show_display_notification


class EstateProperty(models.Model):
    _name = "estate.property"
    _description = "Real Estate Property"
    _order = "id"

    # state_machine = EstatePropertyStateChart()
    name = fields.Char(required=True)
    description = fields.Text()
    postcode = fields.Char()
    date_availability = fields.Date(
        copy=False,
        default=lambda self: fields.Date.add(fields.Date.today(), months=3),
    )
    expected_price = fields.Float(required=True)
    selling_price = fields.Float(readonly=True, copy=False)
    bedrooms = fields.Integer(default=2)
    living_area = fields.Integer()
    facades = fields.Integer()
    garage = fields.Boolean()
    garden = fields.Boolean()
    garden_area = fields.Integer()
    active = fields.Boolean(default=True)
    buyer = fields.Many2one("res.partner", copy=False)
    tag_ids = fields.Many2many("estate.property.tag", string="Tags")
    offer_ids = fields.One2many("estate.property.offer", "property_id", string="Offers")
    total_area = fields.Float(compute="_compute_total_area")
    best_price = fields.Float(compute="_compute_best_price")
    validity = fields.Integer(default=1)
    status = fields.Selection(
        [
            ("pending", "Pending"),
            ("sold", "Sold"),
            ("cancel", "Cancel"),
        ],
        default="pending",
        copy=False,
    )
    property_status = fields.Selection(
        [
            ("sold", "Sell"),
            ("cancel", "Cancel"),
        ],
        default="",
        copy=False,
    )
    date_deadline = fields.Date(
        compute="_compute_date_deadline",
        inverse="_inverse_date_deadline",
    )
    create_date = fields.Date(
        copy=False,
        default=fields.Date.today(),
        readonly=True,
    )
    salesperson = fields.Many2one(
        "res.users", string="Salesperson", default=lambda self: self.env.user
    )
    state = fields.Selection(
        selection=[
            ("new", "New"),
            ("offer_received", "Offer Received"),
            ("offer_accepted", "Offer Accepted"),
            ("sold", "Sold"),
            ("canceled", "Canceled"),
        ],
        required=True,
        default="new",
        copy=False,
    )
    garden_orientation = fields.Selection(
        selection=[
            ("north", "North"),
            ("south", "South"),
            ("east", "East"),
            ("west", "West"),
        ],
    )

    @api.depends("living_area", "garden_area")
    def _compute_total_area(self):
        for record in self:
            record.total_area = record.living_area + record.garden_area

    @api.depends("offer_ids")
    def _compute_best_price(self):
        for record in self:
            record.best_price = (
                max(record.offer_ids.mapped("price")) if record.offer_ids else 0.0
            )

    @api.depends("validity", "create_date")
    def _compute_date_deadline(self):
        for record in self:
            if record.create_date:
                record.date_deadline = fields.Date.add(
                    record.create_date, days=record.validity
                )
            else:
                record.date_deadline = False

    def _inverse_date_deadline(self):
        for record in self:
            if record.create_date and record.date_deadline:
                record.validity = (record.date_deadline - record.create_date).days

    @api.onchange("garden")
    def _onchange_garden(self):
        if self.garden:
            self.garden_area = 10
            self.garden_orientation = "north"
        else:
            self.garden_area = None
            self.garden_orientation = None

    @api.constrains("expected_price")
    def _check_expected_price(self):
        for record in self:
            if record.expected_price <= 0:
                raise ValidationError("The expected price must be greater than 0.")

    @api.constrains("selling_price")
    def _check_selling_price(self):
        for record in self:
            if not record.selling_price >= 0:
                raise ValidationError("The selling price must be greater than 0.")

    def sell_property(self):
        for record in self:
            if record.status == "sold":
                return show_display_notification(
                    title="Sold",
                    message="Cannot sell a property that has already been sold.",
                    type="warning",
                    sticky=False,
                )
            elif record.status == "cancel":
                return show_display_notification(
                    title="",
                    message="The property has already been canceled.",
                    type="warning",
                    sticky=False,
                )
            else:
                record.status = "sold"
                return show_display_notification(
                    title="",
                    message="Your property has been sold successfully!",
                    type="success",
                    sticky=False,
                )

    def cancel_property(self):
        for record in self:
            if record.status == "cancel":
                return show_display_notification(
                    title="",
                    message="Cannot cancel a property that has already been canceled.",
                    type="warning",
                    sticky=False,
                )
            elif record.status == "sold":
                return show_display_notification(
                    title="",
                    message="The property has already been canceled.",
                    type="warning",
                    sticky=False,
                )
            else:
                record.status = "cancel"
                return show_display_notification(
                    title="",
                    message="Your property has been cancelled successfully!",
                    type="success",
                    sticky=False,
                )
