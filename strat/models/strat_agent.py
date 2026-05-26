"""Strat agent — GLM-4.7 + MCP tool-calling agentic loop.

Implements the core loop:
    1. Discover MCP tools → convert to GLM function schemas
    2. Send user message + tools to GLM-4.7
    3. If GLM responds with tool_calls → execute via MCP → feed result back
    4. Repeat until GLM returns a plain text response
"""

import json
import logging
import re

from .mcp_client import get_client

_logger = logging.getLogger(__name__)

MAX_TOOL_STEPS = 15

# Phrases the LLM uses when narrating instead of acting.
_ACTION_PLAN_PHRASES = (
    "i'll ",
    "i will ",
    "let me ",
    "i'm going to ",
    "i am going to ",
    "first, i'll ",
    "i can ",
    "i would ",
    "i should ",
    "i need to ",
    "let's ",
    "i shall ",
)


def _looks_like_action_plan(text):
    """Return True if *text* reads like a plan of action rather than a
    completed response (e.g. 'I'll delete the record...')."""
    lower = text.lower().strip()
    if not lower:
        return False
    for phrase in _ACTION_PLAN_PHRASES:
        if phrase in lower:
            return True
    return False


# MCP tool names that modify data, mapped to a short action label.
_WRITE_TOOLS = {
    "create_record": "create",
    "write": "write",
    "update_record": "write",
    "delete_record": "delete",
    "unlink": "delete",
}


def _track_change(changes, tool_name, args, tool_result):
    """Append a ``{model, action, res_ids}`` entry to *changes* if the tool
    is a data-modifying operation."""
    action = _WRITE_TOOLS.get(tool_name)
    if not action:
        return

    model = args.get("model") or args.get("res_model") or ""
    if not model:
        return

    res_ids = []

    # For write/update, the target ID is usually in 'id' or 'ids'
    if action == "write":
        res_ids = [args.get("id")] if args.get("id") else args.get("ids", [])
    # For delete, same pattern
    elif action == "delete":
        res_ids = [args.get("id")] if args.get("id") else args.get("ids", [])
    # For create, try to parse the new ID from the result text
    elif action == "create":
        # MCP tool results typically return the new record ID as text
        result_text = str(tool_result)
        match = re.search(r"\b(\d+)\b", result_text)
        if match:
            res_ids = [int(match.group(1))]

    res_ids = [int(rid) for rid in res_ids if rid is not None]
    changes.append({"model": model, "action": action, "res_ids": res_ids})


def _mcp_to_glm_tools(mcp_tools):
    """Convert MCP tool definitions to GLM function-calling format."""
    out = []
    for tool in mcp_tools:
        out.append(
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool.get(
                        "inputSchema", {"type": "object", "properties": {}}
                    ),
                },
            }
        )
    return out


def run(zai_api_key, zai_base_url, odoo_config, messages):
    """
    Execute the agentic loop.

    Returns a dict ``{text, changes}`` where *changes* is a list of
    ``{model, action, res_ids}`` dicts, or ``None`` when the MCP server
    is unreachable (so the caller can fall back to a plain LLM chat).
    """
    from zai import ZaiClient

    # 1. Connect to MCP and discover tools
    try:
        mcp = get_client(**odoo_config)
    except Exception:
        _logger.exception("MCP connection failed, falling back to plain chat")
        return None

    glm_tools = _mcp_to_glm_tools(mcp.tools) if mcp.tools else None
    _logger.info("Agent starting with %d MCP tools", len(mcp.tools))

    zai_client = ZaiClient(api_key=zai_api_key, base_url=zai_base_url, max_retries=3)

    # Track models/records modified during the loop
    changes = []

    for step in range(MAX_TOOL_STEPS):
        # 2. Call LLM
        kwargs = dict(
            model="glm-4.7",
            messages=messages,
            temperature=0.2,
            max_tokens=2000,
        )
        if glm_tools:
            kwargs["tools"] = glm_tools
            kwargs["tool_choice"] = "auto"

        try:
            resp = zai_client.chat.completions.create(**kwargs)
        except Exception:
            _logger.exception("LLM request failed at step %d", step)
            return {
                "text": "Sorry, I encountered an error contacting the AI service.",
                "changes": changes,
            }

        choice = resp.choices[0]
        msg = choice.message

        # 3. No tool calls → final answer
        if not msg.tool_calls:
            content = msg.content or ""
            # If the LLM narrates an action instead of taking it on the first step,
            # force it to use tools by re-sending with tool_choice=required.
            if step == 0 and glm_tools and _looks_like_action_plan(content):
                _logger.info(
                    "LLM narrated instead of acting (step 0), retrying with tool_choice=required"
                )
                kwargs["tool_choice"] = "required"
                try:
                    resp = zai_client.chat.completions.create(**kwargs)
                except Exception:
                    _logger.exception("LLM retry failed")
                    return {"text": content, "changes": changes}
                choice = resp.choices[0]
                msg = choice.message
                if not msg.tool_calls:
                    return {"text": msg.content or "", "changes": changes}
            else:
                return {"text": content, "changes": changes}

        # 4. Append assistant message with tool_calls to history
        messages.append(
            {
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in msg.tool_calls
                ],
            }
        )

        # 5. Execute each tool call via MCP and feed results back
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments)
            except (json.JSONDecodeError, TypeError):
                args = {}

            tool_name = tc.function.name
            try:
                tool_result = mcp.call_tool(tool_name, args)
                _logger.info(
                    "Step %d: %s(%s) → %s",
                    step,
                    tool_name,
                    json.dumps(args)[:120],
                    str(tool_result)[:200],
                )
                # Track data-modifying operations for live reload
                _track_change(changes, tool_name, args, tool_result)
            except Exception as e:
                tool_result = f"Error calling {tool_name}: {e}"
                _logger.error("Step %d: %s failed: %s", step, tool_name, e)

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": str(tool_result),
                }
            )

    return {
        "text": (
            "I reached the maximum number of tool calls for this request. "
            "Please try a more specific question."
        ),
        "changes": changes,
    }
