import logging

from odoo import api, fields, models

logger = logging.getLogger(__name__)


class Strat2Message(models.Model):
    _name = "strat2.message"
    _description = "Strat 2.0 Chat Message"
    _order = "create_date asc"

    user_id = fields.Many2one(
        "res.users", string="User", default=lambda self: self.env.user
    )
    message = fields.Text(required=True)
    is_user = fields.Boolean(default=True)

    @api.model
    def send_and_respond(self, message, context=None):
        """Save user message, generate a response, save it, and return it."""
        self.create({"message": message, "is_user": True})

        # TODO: plug in AI backend here
        response_text = self._generate_response(message)

        self.create({"message": response_text, "is_user": False})
        return {"response": response_text}

    @api.model
    def clear_conversation(self):
        """Delete all messages for the current user."""
        self.search([("user_id", "=", self.env.uid)]).unlink()

    @api.model
    def get_conversation(self):
        """Return recent messages for the current user."""
        messages = self.search(
            [("user_id", "=", self.env.uid)], limit=50, order="create_date asc"
        )
        return [{"is_user": m.is_user, "message": m.message} for m in messages]

    def _generate_response(self, message):
        """Placeholder response generator.

        Override or replace this method when integrating an AI backend.
        """
        return f"You said: {message}"
