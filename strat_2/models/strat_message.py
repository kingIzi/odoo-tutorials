import json
import logging
import re
from difflib import SequenceMatcher

from odoo import api, fields, models
from odoo.exceptions import UserError

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

logger = logging.getLogger(__name__)

LM_STUDIO_BASE_URL = "http://10.2.0.2:1234/v1"
LM_STUDIO_API_KEY = "lm-studio"
LM_STUDIO_MODEL = "qwen2.5-7b-instruct"
LM_STUDIO_TEMPERATURE = 0.1
LM_STUDIO_MAX_TOKENS = 512

# System/internal model prefixes to hide from the model list.
_SYSTEM_MODEL_PREFIXES = (
    "ir.",
    "base.",
    "report.",
    "web.",
    "bus.",
    "mail.",
    "pub.",
    "portal.",
    "http.",
    "digest.",
    "iap.",
    "rating.",
    "link.",
    "utm.",
    "snippet.",
    "theme.",
    "html.",
    "base_",
    "l10n_",
)

SYSTEM_PROMPT = (
    "You are Strat 2.0, a friendly AI assistant integrated into Odoo. "
    "You can help users link and unlink Odoo models, and add, remove, "
    "check, and list linked records.\n\n"
    "INSTALLED MODELS:\n"
    "{MODELS_HINT}\n\n"
    "ACTIVE LINKS:\n"
    "{LINKS_HINT}\n\n"
    "HOW TO RESPOND:\n"
    "- If the user wants to LINK two models, respond with ONLY this JSON "
    "(no other text before or after):\n"
    '  {{"action": "link_models", "model_a": "model name", "model_b": "model name"}}\n'
    "- If the user wants to UNLINK two models, respond with ONLY this JSON:\n"
    '  {{"action": "unlink_models", "model_a": "model name", "model_b": "model name"}}\n'
    "- If the user wants to ADD record(s) to a linked model, "
    "respond with ONLY this JSON:\n"
    '  {{"action": "add_entry", "model_a": "model name", "record_a": "record name", '
    '"model_b": "model name", "record_b": "record name(s)"}}\n'
    '  Example: "add property Villa House to employee John Doe" ->\n'
    '  {{"action": "add_entry", "model_a": "Employees", "record_a": "John Doe", '
    '"model_b": "Real Estate Properties", "record_b": "Villa House"}}\n'
    "  For MULTIPLE records, use a comma-separated list:\n"
    '  {{"action": "add_entry", "model_a": "Employees", "record_a": "John Doe", '
    '"model_b": "Real Estate Properties", "record_b": "Le Sapin, Kirikou Hotel"}}\n'
    "  model_a is the target model (added TO), record_a is the target record.\n"
    "  model_b is the source model, record_b is one or more comma-separated names.\n"
    "- If the user wants to REMOVE a linked record or all linked records, "
    "respond with ONLY this JSON:\n"
    '  {{"action": "remove_entry", "model_a": "model name", "record_a": "record name", '
    '"model_b": "model name"}}\n'
    "  Use record_b only if removing a SPECIFIC record:\n"
    '  {{"action": "remove_entry", "model_a": "model name", "record_a": "record name", '
    '"model_b": "model name", "record_b": "specific record name(s)"}}\n'
    '  Example: "remove all properties from employee John Doe" ->\n'
    '  {{"action": "remove_entry", "model_a": "Employees", "record_a": "John Doe", '
    '"model_b": "Real Estate Properties"}}\n'
    '  Example: "remove property Villa House from employee John Doe" ->\n'
    '  {{"action": "remove_entry", "model_a": "Employees", "record_a": "John Doe", '
    '"model_b": "Real Estate Properties", "record_b": "Villa House"}}\n'
    '  For MULTIPLE records: "record_b": "Le Sapin, Kirikou Hotel"\n'
    "  model_a is the model to remove FROM, model_b is the linked model.\n"
    "  record_b is optional — omit it to remove ALL.\n"
    "- If the user wants to CHECK whether two records are linked, "
    "respond with ONLY this JSON:\n"
    '  {{"action": "check_entry", "model_a": "model name", "record_a": "record name", '
    '"model_b": "model name", "record_b": "record name"}}\n'
    '  Example: "Is Le Sapin linked with Ferre Gola?" ->\n'
    '  {{"action": "check_entry", "model_a": "Real Estate Properties", "record_a": "Le Sapin", '
    '"model_b": "Employees", "record_b": "Ferre Gola"}}\n'
    "  The order of model_a/model_b does not matter for checking.\n"
    "- If the user wants to LIST linked records, "
    "respond with ONLY this JSON:\n"
    '  {{"action": "list_entries", "model_a": "model name", "record_a": "record name", '
    '"model_b": "model name"}}\n'
    '  Example: "list all properties of employee Ferre Gola" ->\n'
    '  {{"action": "list_entries", "model_a": "Employees", "record_a": "Ferre Gola", '
    '"model_b": "Real Estate Properties"}}\n'
    "  record_a is OPTIONAL — omit it to list records linked to ANY "
    "record of model_a.\n"
    '  Example: "list all properties linked to at least one employee" ->\n'
    '  {{"action": "list_entries", "model_a": "Employees", '
    '"model_b": "Real Estate Properties"}}\n'
    "  model_a is the record's model, model_b is the linked model to list.\n"
    "- For model names, you can use either the human-readable name (e.g. "
    "'Employees') or the technical name (e.g. 'hr.employee').\n"
    "- If the request is vague (e.g. 'Link models'), do NOT output JSON. "
    "Ask the user to clarify.\n"
    "- For any other question, respond with normal text.\n\n"
    "RULES:\n"
    "1. When performing an action, output ONLY the JSON. No explanations.\n"
    "2. Keep all responses short and to the point.\n"
    "3. IMPORTANT: Distinguish between actions and queries.\n"
    "   - 'Is X linked with Y?' or 'Does X have Y?' -> check_entry\n"
    "   - 'Show/List all X for Y' or 'What is linked to Y?' -> list_entries\n"
    "   - 'Add X to Y' -> add_entry\n"
    "   - 'Remove X from Y' -> remove_entry\n"
    "   Never treat a question/check as an add/remove action.\n"
    "4. CRITICAL: NEVER answer questions about linked records from memory.\n"
    "   Always use check_entry or list_entries to get the CURRENT state.\n"
    "   Data changes after every add/remove — your memory is STALE.\n"
    "   If the user asks about links, you MUST output a JSON action."
)

MAX_AGENT_STEPS = 3


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
    def send_and_respond(self, message, context=None, form_context=None):
        """Save user message, generate a response, save it, and return it.

        Returns a dict ``{response, changes}`` where *changes* tracks
        data-modifying operations so the frontend can refresh affected views.

        :param form_context: optional dict ``{model, resId, displayName}``
            describing the record currently open in the form view.
        """
        self.create({"message": message, "is_user": True})

        result = self._generate_response(message, form_context=form_context)

        if isinstance(result, dict):
            response_text = result["text"]
            changes = result.get("changes", [])
        else:
            response_text = result
            changes = []

        # Expand link changes to include linked models for frontend refresh
        link_ids = []
        for change in changes:
            if change.get("model") == "strat2.module.link":
                link_ids.extend(change.get("res_ids", []))
        if link_ids:
            for link in self.env["strat2.module.link"].sudo().browse(link_ids):
                if link.exists():
                    changes.append(
                        {"model": link.model_a, "action": "write", "res_ids": []}
                    )
                    changes.append(
                        {"model": link.model_b, "action": "write", "res_ids": []}
                    )

        self.create({"message": response_text, "is_user": False})
        return {"response": response_text, "changes": changes}

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

    # -- model name resolver ------------------------------------------------

    @api.model
    def _resolve_model_name(self, raw_name):
        """Resolve a model identifier to its technical name.

        Accepts technical names (``hr.employee``), human-readable names
        (``Employees``), or partial matches.  Returns the technical name
        as a string, or ``None`` if nothing matches.
        """
        if not raw_name or not raw_name.strip():
            return None
        raw = raw_name.strip()

        IrModel = self.env["ir.model"].sudo()

        # 1. Exact match on technical name
        rec = IrModel.search([("model", "=", raw)], limit=1)
        if rec:
            return rec.model

        # 2. Case-insensitive match on technical name
        rec = IrModel.search([("model", "=ilike", raw)], limit=1)
        if rec:
            return rec.model

        # 3. Exact match on human-readable name
        rec = IrModel.search([("name", "=", raw)], limit=1)
        if rec:
            return rec.model

        # 4. Case-insensitive match on human-readable name
        rec = IrModel.search([("name", "=ilike", raw)], limit=1)
        if rec:
            return rec.model

        # 5. Contains match on human-readable name (e.g. "Real Estate" → "Real Estate Properties")
        rec = IrModel.search([("name", "ilike", raw)], limit=1)
        if rec:
            return rec.model

        # 6. Contains match on technical name (e.g. "employee" → "hr.employee")
        rec = IrModel.search([("model", "ilike", "%" + raw + "%")], limit=1)
        if rec:
            return rec.model

        # 7. Fuzzy similarity match — handles singular/plural, typos, etc.
        raw_lower = raw.lower()
        candidates = IrModel.search_read([("transient", "=", False)], ["model", "name"])
        best_match = None
        best_score = 0.0
        for c in candidates:
            model_tech = c["model"]
            if any(model_tech.startswith(p) for p in _SYSTEM_MODEL_PREFIXES):
                continue
            name_lower = (c["name"] or "").lower()
            if not name_lower:
                continue
            score = SequenceMatcher(None, raw_lower, name_lower).ratio()
            if score > best_score:
                best_score = score
                best_match = model_tech

        logger.debug(
            "Strat 2: resolve '%s' → best='%s' (score=%.2f)",
            raw,
            best_match,
            best_score,
        )
        if best_score >= 0.55 and best_match:
            return best_match

        return None

    # -- system prompt helpers -----------------------------------------------

    @api.model
    def _get_models_hint(self):
        """Build a bullet list of user-facing models for the system prompt."""
        models = (
            self.env["ir.model"]
            .sudo()
            .search_read(
                [("transient", "=", False)],
                ["model", "name"],
                order="name",
            )
        )
        lines = []
        for m in models:
            model_name = m["model"]
            if any(model_name.startswith(p) for p in _SYSTEM_MODEL_PREFIXES):
                continue
            lines.append(f"  - {m['name']} ({model_name})")
        return "\n".join(lines) if lines else "  (No user-facing models found)"

    @api.model
    def _get_links_hint(self):
        """Build a bullet list of active links for the system prompt."""
        links = self.env["strat2.module.link"].sudo().search([("active", "=", True)])
        if not links:
            return "  (No active links)"
        lines = []
        for link in links:
            ir_a = (
                self.env["ir.model"]
                .sudo()
                .search([("model", "=", link.model_a)], limit=1)
            )
            ir_b = (
                self.env["ir.model"]
                .sudo()
                .search([("model", "=", link.model_b)], limit=1)
            )
            name_a = ir_a.name if ir_a else link.model_a
            name_b = ir_b.name if ir_b else link.model_b
            lines.append(f"  - {name_a} ({link.model_a}) <-> {name_b} ({link.model_b})")
        return "\n".join(lines)

    @api.model
    def _resolve_display_name(self, model, res_id):
        """Fetch the display_name of a record, or return None."""
        try:
            rec = self.env[model].sudo().browse(res_id)
            if rec.exists():
                return (
                    getattr(rec, "display_name", None)
                    or getattr(rec, "name", None)
                    or None
                )
        except Exception:
            pass
        return None

    @api.model
    def _build_form_context_hint(self, form_context):
        """Build the CURRENT RECORD CONTEXT block for the system prompt.

        Resolves the human-readable model name and record display name
        so the LLM can map "this employee" → the concrete record.
        """
        if not form_context or not isinstance(form_context, dict):
            return ""

        model = form_context.get("model", "")
        res_id = form_context.get("resId") or form_context.get("res_id")
        display_name = form_context.get("displayName") or form_context.get(
            "display_name"
        )

        if not model or not res_id:
            return ""

        # Resolve the human-readable model label
        ir_model = self.env["ir.model"].sudo().search([("model", "=", model)], limit=1)
        model_label = ir_model.name if ir_model else model

        # Resolve the record display name from the DB (authoritative)
        resolved_name = self._resolve_display_name(model, res_id)
        if resolved_name:
            display_name = resolved_name
        if not display_name:
            display_name = f"(ID {res_id})"

        return (
            "\nCURRENT RECORD CONTEXT:\n"
            f"The user currently has a {model_label} ({model}) form open: "
            f'"{display_name}" (ID: {res_id}).\n'
            'When the user refers to "this record", "this '
            + model_label.lower()
            + '", "here", "linked to this", '
            "or uses similar contextual language, they mean this specific record.\n"
            f'In that case, auto-fill record_a with "{display_name}" '
            f'and model_a with "{model_label}".\n'
        )

    def _build_messages(self, current_message, form_context=None):
        """Build the full message list: system prompt + history + current."""
        system_content = SYSTEM_PROMPT.replace(
            "{MODELS_HINT}", self._get_models_hint()
        ).replace("{LINKS_HINT}", self._get_links_hint())

        # Inject form-record context when available
        ctx_hint = self._build_form_context_hint(form_context)
        if ctx_hint:
            system_content += ctx_hint

        messages = [{"role": "system", "content": system_content}]
        for msg in self.get_conversation():
            role = "user" if msg["is_user"] else "assistant"
            messages.append({"role": role, "content": msg["message"]})
        messages.append({"role": "user", "content": current_message})
        return messages

    # -- action parser -------------------------------------------------------

    @staticmethod
    def _parse_action(text):
        """Try to extract a JSON action from the LLM response.

        Returns a dict with at least an ``action`` key, or ``None``.
        """
        if not text:
            return None

        # Try to find a JSON object containing an "action" key.
        # Handles: raw JSON, JSON inside markdown code blocks, etc.
        candidates = re.findall(r"\{[^{}]*\}", text, re.DOTALL)
        for candidate in candidates:
            try:
                data = json.loads(candidate)
                if isinstance(data, dict) and data.get("action") in (
                    "link_models",
                    "unlink_models",
                    "add_entry",
                    "remove_entry",
                    "check_entry",
                    "list_entries",
                ):
                    return data
            except (json.JSONDecodeError, TypeError):
                continue
        return None

    # -- agent loop ----------------------------------------------------------

    def _generate_response(self, message, form_context=None):
        """Run the agent loop: call Qwen, parse actions, execute if needed."""
        if OpenAI is None:
            raise UserError(
                "The 'openai' package is not installed. "
                "Install it with: pip install openai"
            )

        try:
            client = OpenAI(
                base_url=LM_STUDIO_BASE_URL,
                api_key=LM_STUDIO_API_KEY,
            )
        except Exception:
            logger.exception("Failed to create OpenAI client")
            raise UserError("Could not connect to the AI model.")

        messages = self._build_messages(message, form_context=form_context)
        changes = []

        for step in range(MAX_AGENT_STEPS):
            try:
                resp = client.chat.completions.create(
                    model=LM_STUDIO_MODEL,
                    messages=messages,
                    temperature=LM_STUDIO_TEMPERATURE,
                    max_tokens=LM_STUDIO_MAX_TOKENS,
                )
            except Exception:
                logger.exception("LLM request failed at step %d", step)
                return {
                    "text": "Sorry, I encountered an error contacting the AI service.",
                    "changes": changes,
                }

            text = resp.choices[0].message.content or ""
            action = self._parse_action(text)

            # No action detected → this is the final response
            if not action:
                return {"text": text, "changes": changes}

            # Execute the action
            action_name = action["action"]
            if action_name == "link_models":
                result_msg = self._execute_link_models(action, changes)
            elif action_name == "unlink_models":
                result_msg = self._execute_unlink_models(action, changes)
            elif action_name == "add_entry":
                result_msg = self._execute_add_entry(action, changes)
            elif action_name == "remove_entry":
                result_msg = self._execute_remove_entry(action, changes)
            elif action_name == "check_entry":
                result_msg = self._execute_check_entry(action)
            elif action_name == "list_entries":
                result_msg = self._execute_list_entries(action)
            else:
                result_msg = f"Unknown action: {action_name}"

            # Query actions (check_entry, list_entries) are already
            # formatted for the user — return directly without a second
            # LLM call that would rewrite/strip the formatting.
            if action_name in ("check_entry", "list_entries"):
                return {"text": result_msg, "changes": changes}

            # Mutating actions: feed the result back to the LLM so it can
            # generate a user-friendly confirmation message.
            messages.append({"role": "assistant", "content": text})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"The action was executed. Result:\n{result_msg}\n\n"
                        "Now reply to the user with a short confirmation of "
                        "what was done. Do not output JSON."
                    ),
                }
            )

        return {
            "text": "I reached the maximum number of steps. Please try again.",
            "changes": changes,
        }

    # -- helpers (record lookup) --------------------------------------------

    @api.model
    def _find_record_by_name(self, model_name, record_name):
        """Find a record by name using Odoo's name_search.

        Falls back to display_name and name field searches if name_search
        returns nothing.
        """
        Model = self.env[model_name].sudo()

        # 1. name_search respects _rec_name and is the standard API
        results = Model.name_search(record_name, operator="ilike", limit=5)
        if results:
            return Model.browse(results[0][0])

        # 2. Fallback: search on display_name
        try:
            rec = Model.search([("display_name", "ilike", record_name)], limit=1)
            if rec:
                return rec
        except Exception:
            pass

        # 3. Fallback: search on name field directly
        try:
            rec = Model.search([("name", "ilike", record_name)], limit=1)
            if rec:
                return rec
        except Exception:
            pass

        return None

    # -- tool: link_models ---------------------------------------------------

    def _execute_link_models(self, args, changes):
        """Create a strat2.module.link record."""
        raw_a = args.get("model_a", "")
        raw_b = args.get("model_b", "")

        if not raw_a or not raw_b:
            return "Error: model_a and model_b are required."

        # Resolve names — the LLM may pass human-readable names
        model_a = self._resolve_model_name(raw_a)
        model_b = self._resolve_model_name(raw_b)

        if not model_a:
            return f"Error: Could not find any model matching '{raw_a}'."
        if not model_b:
            return f"Error: Could not find any model matching '{raw_b}'."

        # Check for duplicate (in either direction)
        existing = (
            self.env["strat2.module.link"].sudo()._find_existing_link(model_a, model_b)
        )
        if existing:
            return (
                f"Error: A link between '{model_a}' and '{model_b}' already exists "
                f"(link: '{existing.name}', ID: {existing.id}). "
                f"Two models can only be linked once."
            )

        # Build a human-readable label from model names
        def _model_label(model_tech):
            ir = (
                self.env["ir.model"]
                .sudo()
                .search([("model", "=", model_tech)], limit=1)
            )
            return ir.name if ir else model_tech

        name = f"{_model_label(model_a)} - {_model_label(model_b)}"

        try:
            link = (
                self.env["strat2.module.link"]
                .sudo()
                .create(
                    {
                        "name": name,
                        "model_a": model_a,
                        "model_b": model_b,
                    }
                )
            )
            changes.append(
                {
                    "model": "strat2.module.link",
                    "action": "create",
                    "res_ids": [link.id],
                }
            )
            return (
                f"Successfully created link '{name}' "
                f"(ID: {link.id}) between {model_a} and {model_b}. "
                f"A new tab has been added to both models' form views."
            )
        except Exception as e:
            logger.exception("Failed to create link")
            return f"Error creating link: {e}"

    # -- tool: unlink_models -------------------------------------------------

    def _execute_unlink_models(self, args, changes):
        """Remove a strat2.module.link and all its database artifacts."""
        raw_a = args.get("model_a", "")
        raw_b = args.get("model_b", "")

        if not raw_a or not raw_b:
            return "Error: model_a and model_b are required."

        # Resolve names — the LLM may pass human-readable names
        model_a = self._resolve_model_name(raw_a)
        model_b = self._resolve_model_name(raw_b)

        if not model_a:
            return f"Error: Could not find any model matching '{raw_a}'."
        if not model_b:
            return f"Error: Could not find any model matching '{raw_b}'."

        # Find the existing link (in either direction)
        link = (
            self.env["strat2.module.link"].sudo()._find_existing_link(model_a, model_b)
        )
        if not link:
            return (
                f"Error: No link found between '{model_a}' and '{model_b}'. "
                f"Nothing to unlink."
            )

        link_name = link.name
        link_id = link.id

        # Save model names before unlink (they're needed for changes tracking)
        linked_model_a = link.model_a
        linked_model_b = link.model_b

        try:
            link.unlink()
            changes.append(
                {
                    "model": "strat2.module.link",
                    "action": "delete",
                    "res_ids": [link_id],
                    # Include linked models so frontend refreshes both
                    "linked_models": [linked_model_a, linked_model_b],
                }
            )
            return (
                f"Successfully removed link '{link_name}' (ID: {link_id}) "
                f"between {linked_model_a} and {linked_model_b}. "
                f"The notebook tab, custom field, and relation table have been deleted."
            )
        except Exception as e:
            logger.exception("Failed to unlink")
            return f"Error unlinking: {e}"

    # -- tool: add_entry ----------------------------------------------------

    def _execute_add_entry(self, args, changes):
        """Add record(s) from one model to another via an existing link.

        record_b can be a single name or a comma-separated list of names.
        """
        raw_a = args.get("model_a", "")
        raw_b = args.get("model_b", "")
        record_name_a = args.get("record_a", "")
        record_name_b = args.get("record_b", "")

        if not raw_a or not raw_b:
            return "Error: model_a and model_b are required."
        if not record_name_a or not record_name_b:
            return "Error: record_a and record_b are required."

        model_a = self._resolve_model_name(raw_a)
        model_b = self._resolve_model_name(raw_b)

        if not model_a:
            return f"Error: Could not find any model matching '{raw_a}'."
        if not model_b:
            return f"Error: Could not find any model matching '{raw_b}'."

        link = (
            self.env["strat2.module.link"].sudo()._find_existing_link(model_a, model_b)
        )
        if not link:
            return (
                f"Error: No active link found between '{model_a}' and '{model_b}'. "
                f"You need to link the models first before adding entries."
            )

        record_a = self._find_record_by_name(model_a, record_name_a)
        if not record_a or not record_a.exists():
            return (
                f"Error: Could not find a record matching '{record_name_a}' "
                f"in {model_a}."
            )

        field_name = f"x_strat2_link_{link.id}"
        display_a = getattr(record_a, "display_name", None) or record_name_a

        # Split record_b on commas to support multiple records
        names_b = [n.strip() for n in record_name_b.split(",") if n.strip()]

        added = []
        failed = []
        try:
            for name in names_b:
                record_b = self._find_record_by_name(model_b, name)
                if not record_b or not record_b.exists():
                    failed.append(name)
                    continue
                # Skip if already linked
                if record_b.id in record_a[field_name].ids:
                    failed.append(f"{name} (already linked)")
                    continue
                record_a.write({field_name: [(4, record_b.id)]})
                display_b = getattr(record_b, "display_name", None) or name
                added.append(display_b)
                changes.append(
                    {"model": model_b, "action": "write", "res_ids": [record_b.id]}
                )

            if added:
                changes.append(
                    {"model": model_a, "action": "write", "res_ids": [record_a.id]}
                )

            parts = []
            if added:
                names_str = ", ".join(f"'{n}'" for n in added)
                parts.append(
                    f"Successfully added {names_str} ({model_b}) to "
                    f"'{display_a}' ({model_a})."
                )
            if failed:
                failed_str = ", ".join(f"'{n}'" for n in failed)
                parts.append(f"Could not add: {failed_str}.")

            return " ".join(parts) if parts else "No records to add."
        except Exception as e:
            logger.exception("Failed to add entry")
            return f"Error adding entry: {e}"

    # -- tool: remove_entry -------------------------------------------------

    def _execute_remove_entry(self, args, changes):
        """Remove linked record(s) from an existing many2many link.

        Supports two modes:
        - Remove ALL linked records of model_b from record_a
          (record_b is omitted/empty).
        - Remove a SPECIFIC record_b from record_a
          (record_b is provided).
        """
        raw_a = args.get("model_a", "")
        raw_b = args.get("model_b", "")
        record_name_a = args.get("record_a", "")
        record_name_b = args.get("record_b", "")

        if not raw_a or not raw_b:
            return "Error: model_a and model_b are required."
        if not record_name_a:
            return "Error: record_a is required."

        # Resolve model names
        model_a = self._resolve_model_name(raw_a)
        model_b = self._resolve_model_name(raw_b)

        if not model_a:
            return f"Error: Could not find any model matching '{raw_a}'."
        if not model_b:
            return f"Error: Could not find any model matching '{raw_b}'."

        # Find the existing link
        link = (
            self.env["strat2.module.link"].sudo()._find_existing_link(model_a, model_b)
        )
        if not link:
            return f"Error: No active link found between '{model_a}' and '{model_b}'."

        # Find the target record (the one to remove FROM)
        record_a = self._find_record_by_name(model_a, record_name_a)
        if not record_a or not record_a.exists():
            return (
                f"Error: Could not find a record matching '{record_name_a}' "
                f"in {model_a}."
            )

        field_name = f"x_strat2_link_{link.id}"
        display_a = getattr(record_a, "display_name", None) or record_name_a

        try:
            if record_name_b:
                # Remove specific linked record(s) — comma-separated
                names_b = [n.strip() for n in record_name_b.split(",") if n.strip()]
                removed = []
                for name in names_b:
                    record_b = self._find_record_by_name(model_b, name)
                    if not record_b or not record_b.exists():
                        continue
                    display_b = getattr(record_b, "display_name", None) or name
                    # Odoo command (3, id) — unlink one record from many2many
                    record_a.write({field_name: [(3, record_b.id)]})
                    changes.append(
                        {"model": model_b, "action": "write", "res_ids": [record_b.id]}
                    )
                    removed.append(display_b)

                if removed:
                    changes.append(
                        {"model": model_a, "action": "write", "res_ids": [record_a.id]}
                    )
                    names_str = ", ".join(f"'{n}'" for n in removed)
                    return (
                        f"Successfully removed {names_str} ({model_b}) "
                        f"from '{display_a}' ({model_a})."
                    )
                return f"None of the specified records were found in {model_b}."
            else:
                # Remove ALL linked records of model_b from record_a
                linked_ids = record_a[field_name].ids
                if not linked_ids:
                    return (
                        f"'{display_a}' ({model_a}) has no linked "
                        f"{model_b} records to remove."
                    )
                count = len(linked_ids)

                # Odoo command (5,) — unlink ALL records from many2many
                record_a.write({field_name: [(5,)]})
                changes.append(
                    {"model": model_a, "action": "write", "res_ids": [record_a.id]}
                )
                changes.extend(
                    {"model": model_b, "action": "write", "res_ids": [rid]}
                    for rid in linked_ids
                )
                return (
                    f"Successfully removed {count} linked {model_b} record(s) "
                    f"from '{display_a}' ({model_a})."
                )
        except Exception as e:
            logger.exception("Failed to remove entry")
            return f"Error removing entry: {e}"

    # -- tool: check_entry --------------------------------------------------

    def _execute_check_entry(self, args):
        """Check whether two specific records are linked via an existing link.

        Returns a human-readable yes/no answer.
        """
        raw_a = args.get("model_a", "")
        raw_b = args.get("model_b", "")
        record_name_a = args.get("record_a", "")
        record_name_b = args.get("record_b", "")

        if not raw_a or not raw_b:
            return "Error: model_a and model_b are required."
        if not record_name_a or not record_name_b:
            return "Error: record_a and record_b are required."

        model_a = self._resolve_model_name(raw_a)
        model_b = self._resolve_model_name(raw_b)

        if not model_a:
            return f"Error: Could not find any model matching '{raw_a}'."
        if not model_b:
            return f"Error: Could not find any model matching '{raw_b}'."

        link = (
            self.env["strat2.module.link"].sudo()._find_existing_link(model_a, model_b)
        )
        if not link:
            return (
                f"No: there is no active link between {model_a} and {model_b}, "
                f"so the records cannot be linked."
            )

        record_a = self._find_record_by_name(model_a, record_name_a)
        if not record_a or not record_a.exists():
            return (
                f"Error: Could not find a record matching '{record_name_a}' "
                f"in {model_a}."
            )

        record_b = self._find_record_by_name(model_b, record_name_b)
        if not record_b or not record_b.exists():
            return (
                f"Error: Could not find a record matching '{record_name_b}' "
                f"in {model_b}."
            )

        field_name = f"x_strat2_link_{link.id}"
        display_a = getattr(record_a, "display_name", None) or record_name_a
        display_b = getattr(record_b, "display_name", None) or record_name_b

        # Check if record_b is in record_a's linked records.
        # We try both sides since either could hold the field.
        linked_ids = record_a[field_name].ids
        if record_b.id in linked_ids:
            return (
                f"Yes: '{display_a}' ({model_a}) is linked with "
                f"'{display_b}' ({model_b})."
            )

        return (
            f"No: '{display_a}' ({model_a}) is NOT linked with "
            f"'{display_b}' ({model_b})."
        )

    # -- tool: list_entries -------------------------------------------------

    def _execute_list_entries(self, args):
        """List linked records of model_b.

        Two modes:
        - record_a provided: list records linked to that specific record.
        - record_a omitted: list ALL model_b records linked to ANY model_a record.
        """
        raw_a = args.get("model_a", "")
        raw_b = args.get("model_b", "")
        record_name_a = args.get("record_a", "")

        if not raw_a or not raw_b:
            return "Error: model_a and model_b are required."

        model_a = self._resolve_model_name(raw_a)
        model_b = self._resolve_model_name(raw_b)

        if not model_a:
            return f"Error: Could not find any model matching '{raw_a}'."
        if not model_b:
            return f"Error: Could not find any model matching '{raw_b}'."

        link = (
            self.env["strat2.module.link"].sudo()._find_existing_link(model_a, model_b)
        )
        if not link:
            return f"No active link found between {model_a} and {model_b}."

        field_name = f"x_strat2_link_{link.id}"

        if record_name_a:
            # --- Specific record mode ---
            record_a = self._find_record_by_name(model_a, record_name_a)
            if not record_a or not record_a.exists():
                return (
                    f"Error: Could not find a record matching '{record_name_a}' "
                    f"in {model_a}."
                )

            display_a = getattr(record_a, "display_name", None) or record_name_a
            linked_records = record_a[field_name]
            if not linked_records:
                return f"'{display_a}' ({model_a}) has no linked {model_b} records."

            lines = [f"Linked {model_b} records for '{display_a}' ({model_a}):\n"]
            lines.append("| # | Name |")
            lines.append("|---|------|")
            for idx, rec in enumerate(linked_records, 1):
                rec_name = (
                    getattr(rec, "display_name", None)
                    or getattr(rec, "name", None)
                    or "(unnamed)"
                )
                lines.append(f"| {idx} | {rec_name} |")

            return "\n".join(lines)

        else:
            # --- All-records mode: collect every model_b linked to any model_a ---
            ModelA = self.env[model_a].sudo()
            all_a_records = ModelA.search([(field_name, "!=", False)])
            if not all_a_records:
                return f"No {model_a} records have any linked {model_b} records."

            seen_ids = set()
            unique_records = self.env[model_b].sudo()
            for rec_a in all_a_records:
                for rec_b in rec_a[field_name]:
                    if rec_b.id not in seen_ids:
                        seen_ids.add(rec_b.id)
                        unique_records |= rec_b

            if not unique_records:
                return f"No {model_b} records are linked to any {model_a}."

            lines = [f"All {model_b} records linked to at least one {model_a}:\n"]
            lines.append("| # | Name |")
            lines.append("|---|------|")
            for idx, rec in enumerate(unique_records, 1):
                rec_name = (
                    getattr(rec, "display_name", None)
                    or getattr(rec, "name", None)
                    or "(unnamed)"
                )
                lines.append(f"| {idx} | {rec_name} |")

            return "\n".join(lines)
