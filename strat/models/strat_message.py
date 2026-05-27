import logging
import os
from pathlib import Path

from odoo import api, fields, models

try:
    from zai import ZaiClient
except ImportError:
    ZaiClient = None

from .mcp_client import test_connection as mcp_test_connection
from .strat_agent import run as agent_run
from .utils import get_api_key, get_odoo_config, is_mcp_configured, save_odoo_config

logger = logging.getLogger(__name__)

ZAI_BASE_URL = "https://api.z.ai/api/coding/paas/v4/"
# Prefixes of internal/system models to exclude from the dynamic model list.
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
    "You are Strat, a friendly and concise AI assistant integrated into Odoo. "
    "You have access to Odoo data through MCP tools. "
    "When users ask about contacts, invoices, products, or any Odoo data, "
    "use the available tools to retrieve real information. "
    "Be concise, friendly, and connect data across modules when relevant.\n\n"
    "CRITICAL BEHAVIOR RULES:\n"
    "1. When the user asks you to DO something (create, delete, update, link), you MUST "
    "call the appropriate tool(s) — do NOT just describe what you would do.\n"
    "2. After every action (create/delete/update), ALWAYS confirm the result in your "
    "final response. Say what you did and whether it succeeded, including any new IDs "
    "or names. For example: 'Done! I deleted link #30 and created a new link (ID: 42) "
    "between employees and properties.'\n"
    "3. If a tool returns an error, report the error clearly and suggest next steps.\n"
    "4. Never say 'I will...' or 'Let me...' — just do it via tools, then confirm the result.\n\n"
    "SEARCHING FOR DATA — follow these rules strictly:\n"
    "• The following models are installed in this Odoo instance:\n"
    "{MODELS_HINT}\n"
    "  For these models, go straight to search_records — do NOT call list_models first.\n"
    "• If the user asks about something NOT in the list above, call list_models to "
    "discover the exact technical model name.\n"
    "• If a search returns no results, try related models before telling the user "
    "the record doesn't exist. For example, if 'Kirikou Hotel' is not in res.partner, "
    "try estate.property, product.template, project.project, etc.\n"
    "• NEVER say a record doesn't exist or ask the user which model it's in — "
    "use tools to find it yourself.\n"
    "• NEVER say a module or model doesn't exist unless you have actually searched "
    "for records and gotten zero results.\n\n"
    "LINKING MODULES\n"
    "When asked to link two models (e.g. 'link employees and properties'), do ONLY "
    "the following:\n"
    "1. Find the technical model names with list_models if unsure.\n"
    "2. create_record('strat.module.link', {name, model_a, model_b}) to define the link.\n"
    "That is ALL you should do. This automatically adds a new notebook tab to the "
    "form views of both models. The user can then open either form, go to the new tab, "
    "and click 'Add a line' to select records from the other model.\n"
    "IMPORTANT: Do NOT create strat.module.link.line records. Do NOT try to link "
    "specific records programmatically. The linking is done by the user through "
    "the Odoo UI after you create the link definition.\n\n"
    "FORMAT RULES — follow them strictly:\n"
    "• When presenting rows of data (4+ items with multiple fields) use a markdown table: "
    "| Column | Column | then |---|---| then data rows.\n"
    "• Use bullet points (- item) for: short lists, summaries, key facts, features, "
    "steps, recommendations, or any info that benefits from quick scanning.\n"
    "• Prefer bullet points over plain paragraphs whenever listing or enumerating things.\n"
    "• Use **bold** for column names, key values, or emphasis.\n"
    "• Keep responses short. Do NOT wrap tables in code blocks.\n"
    "• Never show raw IDs unless the user asks."
)


class StratMessage(models.Model):
    _name = "strat.message"
    _description = "Strat Chat Message"
    _order = "create_date asc"

    user_id = fields.Many2one(
        "res.users", string="User", default=lambda self: self.env.user
    )
    message = fields.Text(required=True)
    is_user = fields.Boolean(default=True)

    # -- MCP configuration (called from frontend) ----------------------------

    @api.model
    def get_mcp_config(self):
        """Return current MCP connection settings from .env.

        The password is masked for display in the UI.
        Returns a dict with configured status and current values.
        """
        user = get_odoo_config_value("ODOO_USER") or ""
        password = get_odoo_config_value("ODOO_PASSWORD") or ""
        url = get_odoo_config_value("ODOO_URL") or ""
        db = get_odoo_config_value("ODOO_DB") or ""
        yolo = get_odoo_config_value("ODOO_YOLO") or "read"

        return {
            "configured": bool(user and password),
            "odoo_user": user,
            "odoo_password": password,
            "odoo_url": url,
            "odoo_db": db,
            "odoo_yolo": yolo,
        }

    @api.model
    def save_mcp_config(self, username, password, url=None, database=None, yolo=None):
        """Test the MCP connection first, then save to .env only on success.

        Auto-detects URL and database from the running Odoo instance if not provided.
        Returns ``{success, error?, config}``.
        """
        # Auto-detect URL and DB from current Odoo instance
        if not url:
            try:
                from odoo.http import request

                url = request.httprequest.host_url.rstrip("/")
            except Exception:
                url = "http://localhost:8069"
        if not database:
            database = self.env.cr.dbname
        if not yolo:
            yolo = "read"

        # Test the connection BEFORE saving anything
        result = mcp_test_connection(
            odoo_url=url,
            odoo_db=database,
            odoo_user=username,
            odoo_password=password,
            odoo_yolo=yolo,
        )

        config = {
            "odoo_user": username,
            "odoo_password": password,
            "odoo_url": url,
            "odoo_db": database,
            "odoo_yolo": yolo,
        }

        if result is True:
            # Connection OK — persist credentials to .env
            save_odoo_config(
                username=username,
                password=password,
                url=url,
                database=database,
                yolo=yolo,
            )
            return {"success": True, "config": config}
        else:
            # Connection failed — do NOT save; return friendly error
            error_msg = self._friendly_mcp_error(result)
            return {"success": False, "error": error_msg, "config": config}

    @api.model
    def _friendly_mcp_error(self, raw_error):
        """Turn a raw MCP exception string into a short, user-friendly message."""
        err = str(raw_error).lower()
        if "access denied" in err or "authentication" in err or "403" in err:
            return "Username or password is incorrect."
        if "connection refused" in err or "connectionerror" in err:
            return "Could not reach the Odoo server. Check that Odoo is running."
        if "database" in err and ("not found" in err or "does not exist" in err):
            return "Database not found. Check the database name."
        if "timeout" in err:
            return "Connection timed out. The server took too long to respond."
        # Fallback: first line only, stripped of traceback noise
        first_line = str(raw_error).strip().split("\n")[0]
        if len(first_line) > 120:
            first_line = first_line[:120] + "..."
        return first_line

    # -- chat methods --------------------------------------------------------

    @api.model
    def send_and_respond(self, message, context=None):
        """Save user message, generate a response, save it, and return it.

        Returns a dict ``{response, changes}`` where *changes* is a list of
        ``{model, action, res_ids}`` dicts for data-modifying operations.

        :param context: optional dict with current page info (model, res_id)
        """
        self.create({"message": message, "is_user": True})
        result = self._generate_response(message, page_context=context or {})

        # Agent returns a dict with text + changes; fallback returns a plain string
        if isinstance(result, dict):
            response_text = result["text"]
            changes = result.get("changes", [])
        else:
            response_text = result
            changes = []

        # When a strat.module.link is created, expand the changes to include
        # the linked models so the frontend reloads their form views.
        link_ids = []
        for change in changes:
            if (
                change.get("model") == "strat.module.link"
                and change.get("action") == "create"
            ):
                link_ids.extend(change.get("res_ids", []))
        if link_ids:
            for link in self.env["strat.module.link"].sudo().browse(link_ids):
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

    # -- message building --------------------------------------------------

    @api.model
    def _get_models_hint(self):
        """Query ir.model for user-facing models and return a compact mapping.

        Scans all non-transient models in the database, filters out system/internal
        ones, and returns a bullet list like ``"  - Name (model.name)"``.
        This is injected into the system prompt so the LLM knows which models
        are available without calling list_models first.
        """
        IrModel = self.env["ir.model"].sudo()
        models = IrModel.search_read(
            [("transient", "=", False)],
            ["model", "name"],
            order="name",
        )

        lines = []
        for m in models:
            model_name = m["model"]
            if any(model_name.startswith(p) for p in _SYSTEM_MODEL_PREFIXES):
                continue
            lines.append(f"  - {m['name']} ({model_name})")

        return "\n".join(lines) if lines else "  (No user-facing models found)"

    def _build_messages(self, current_message, page_context=None):
        """Build the full message list for the LLM (system + history + current).

        If *page_context* is provided (e.g. {"model": "hr.employee", "res_id": 5}),
        a context block is appended to the system prompt so the LLM knows what
        record the user is currently viewing.
        """
        system_content = SYSTEM_PROMPT.replace("{MODELS_HINT}", self._get_models_hint())
        if page_context:
            ctx_parts = []
            model = page_context.get("model", "")
            if model:
                # Human-readable model name from ir.model
                ir_model = (
                    self.env["ir.model"].sudo().search([("model", "=", model)], limit=1)
                )
                model_label = ir_model.name or model if ir_model else model
                ctx_parts.append(
                    f"The user is currently viewing a **{model_label}** ({model})"
                )
            res_id = page_context.get("res_id")
            if res_id:
                # Fetch the display name of the record
                try:
                    record = self.env[model].browse(res_id)
                    display_name = record.display_name or f"#{res_id}"
                except Exception:
                    display_name = f"#{res_id}"
                ctx_parts.append(f"record: **{display_name}** (id: {res_id})")
            if ctx_parts:
                system_content += (
                    "\n\nCURRENT PAGE CONTEXT\n" + "\n".join(ctx_parts) + "\n"
                    "When the user says 'this record', 'this employee', 'it', etc., "
                    "they are referring to the record above. "
                    "Use the model name and id to target your tool calls correctly."
                )

        messages = [{"role": "system", "content": system_content}]
        for msg in self.get_conversation():
            role = "user" if msg["is_user"] else "assistant"
            messages.append({"role": role, "content": msg["message"]})
        messages.append({"role": "user", "content": current_message})
        return messages

    # -- response generation -----------------------------------------------

    def _generate_response(self, message, page_context=None):
        """Generate a response using GLM-4.7.

        Tries the MCP-powered agent first (tool calling).
        Falls back to a plain LLM chat if MCP is unavailable.
        """
        api_key = get_api_key()
        if not api_key:
            return (
                "AI service is not configured. Please set ZAI_API_KEY in the .env file."
            )

        if ZaiClient is None:
            return "AI service is not available. Please install the zai-sdk package."

        client = ZaiClient(api_key=api_key, base_url=ZAI_BASE_URL, max_retries=3)
        odoo_config = get_odoo_config()

        messages = self._build_messages(message, page_context=page_context)
        if odoo_config:
            try:
                result = agent_run(client, odoo_config, messages)
                if result is not None:
                    return result  # dict {text, changes}
            except Exception:
                logger.exception("Agent failed, falling back to plain chat")

        # Fallback: plain LLM chat without tools
        try:
            response = client.chat.completions.create(
                model="glm-4.7",
                messages=messages,
                temperature=0.2,
                max_tokens=1000,
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.exception("Failed to generate response from GLM-4.7")
            return f"Sorry, something went wrong: {e}"


def get_odoo_config_value(key):
    """Read a single value from .env (helper exposed to model methods)."""
    from .utils import read_env_value

    return read_env_value(key)
