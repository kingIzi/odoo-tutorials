import logging
import os
from pathlib import Path

from odoo import api, fields, models

logger = logging.getLogger(__name__)

ZAI_BASE_URL = "https://api.z.ai/api/coding/paas/v4/"
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
    "• When looking for a record by name, NEVER guess which model it's in. "
    "Always call list_models first to discover what models exist in this Odoo instance.\n"
    "• Users may refer to models by informal names (e.g. 'real estate properties', 'properties', "
    "'estate properties' → estate.property; 'employees' → hr.employee; 'contacts' → res.partner; "
    "'invoices' → account.move; 'products' → product.template; 'sales orders' → sale.order). "
    "Use list_models to find the exact technical name.\n"
    "• If a search in one model returns no results, try related models before telling the user "
    "the record doesn't exist. For example, if 'Kirikou Hotel' is not in res.partner, "
    "search estate.property, product.template, project.project, etc.\n"
    "• NEVER say a record doesn't exist or ask the user which model it's in — "
    "use list_models and search to find it yourself.\n\n"
    "LINKING MODULES\n"
    "When asked to link two models (e.g. 'link employees and properties'), use the "
    "strat.module.link wrapper. Odoo schemas cannot change at runtime, so you must "
    "NOT attempt to create fields or alter views directly.\n"
    "Steps:\n"
    "1. Find the technical model names with list_models if unsure.\n"
    "2. create_record('strat.module.link', {name, model_a, model_b}) to define the link.\n"
    "3. To link specific records: create_record('strat.module.link.line', "
    "{link_id, res_id_a, res_id_b}).\n"
    "4. To show linked records: search 'strat.module.link.line' with "
    "domain [('link_id.model_a','<model>'), ('res_id_a',<id>)]. "
    "The link is bidirectional — model_b/res_id_b works too.\n"
    "5. Use get_record to fetch display details of the linked records.\n\n"
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

    # -- config helpers ----------------------------------------------------

    def _read_env_value(self, key):
        """Read a value from the environment or the module's .env file."""
        val = os.getenv(key)
        if val:
            return val

        env_path = Path(__file__).resolve().parent.parent / ".env"
        if not env_path.exists():
            return None

        prefix = f"{key}="
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith(prefix):
                return line[len(prefix) :].strip().strip('"').strip("'")
        return None

    def _get_api_key(self):
        key = self._read_env_value("ZAI_API_KEY")
        if not key:
            logger.error("ZAI_API_KEY not configured")
        return key

    def _get_odoo_config(self):
        """Read Odoo connection params from .env for the MCP server."""
        odoo_url = self._read_env_value("ODOO_URL")
        if not odoo_url:
            logger.debug("ODOO_URL not configured — agent mode disabled")
            return None
        return {
            "odoo_url": odoo_url,
            "odoo_db": self._read_env_value("ODOO_DB") or "",
            "odoo_user": self._read_env_value("ODOO_USER") or "admin",
            "odoo_password": self._read_env_value("ODOO_PASSWORD") or "admin",
            "odoo_yolo": self._read_env_value("ODOO_YOLO") or "read",
        }

    # -- message building --------------------------------------------------

    def _build_messages(self, current_message, page_context=None):
        """Build the full message list for the LLM (system + history + current).

        If *page_context* is provided (e.g. {"model": "hr.employee", "res_id": 5}),
        a context block is appended to the system prompt so the LLM knows what
        record the user is currently viewing.
        """
        system_content = SYSTEM_PROMPT
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
        try:
            from zai import ZaiClient
        except ImportError:
            logger.error("zai-sdk is not installed")
            return "Sorry, the AI service is not available right now."

        api_key = self._get_api_key()
        if not api_key:
            return "Sorry, the AI service is not configured."

        messages = self._build_messages(message, page_context=page_context)

        # 1) Try the MCP agent (tool-calling loop)
        odoo_config = self._get_odoo_config()
        if odoo_config:
            try:
                from .strat_agent import run as agent_run

                result = agent_run(api_key, ZAI_BASE_URL, odoo_config, messages)
                if result is not None:
                    return result  # dict {text, changes}
            except Exception:
                logger.exception("Agent failed, falling back to plain chat")

        # 2) Fallback: plain LLM chat without tools
        client = ZaiClient(api_key=api_key, base_url=ZAI_BASE_URL, max_retries=3)
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
