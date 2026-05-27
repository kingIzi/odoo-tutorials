"""MCP client — spawns mcp-server-odoo as a subprocess (stdio transport).

Strat manages the MCP server lifecycle itself — no separate process needed.
Communication happens over stdin/stdout using newline-delimited JSON-RPC.
"""

import json
import logging
import os
import subprocess
import threading

_logger = logging.getLogger(__name__)

# Module-level singleton: one MCP server process per Odoo worker.
_client_lock = threading.Lock()
_cached_client = None


def get_client(odoo_url, odoo_db, odoo_user, odoo_password, odoo_yolo="true"):
    """Return a cached MCPClient, starting a fresh one if needed."""
    global _cached_client
    with _client_lock:
        if _cached_client and _cached_client.is_alive():
            return _cached_client
        _cached_client = MCPClient(
            odoo_url=odoo_url,
            odoo_db=odoo_db,
            odoo_user=odoo_user,
            odoo_password=odoo_password,
            odoo_yolo=odoo_yolo,
        ).connect()
        return _cached_client


def test_connection(odoo_url, odoo_db, odoo_user, odoo_password, odoo_yolo="true"):
    """Try to spawn an MCP server and connect.

    Returns ``True`` on success or an error string on failure.
    Does NOT cache the client — used purely for validation.
    """
    try:
        client = MCPClient(
            odoo_url=odoo_url,
            odoo_db=odoo_db,
            odoo_user=odoo_user,
            odoo_password=odoo_password,
            odoo_yolo=odoo_yolo,
        )
        client.connect()
        # If we got here the session is alive
        client.stop()
        return True
    except Exception as exc:
        _logger.warning("MCP test_connection failed: %s", exc)
        return str(exc)


class MCPClient:
    """Spawn ``mcp-server-odoo`` as a child process and speak JSON-RPC over
    stdin/stdout (the same transport Claude Desktop / Zed use)."""

    def __init__(self, odoo_url, odoo_db, odoo_user, odoo_password, odoo_yolo="true"):
        self._env_vars = {
            "ODOO_URL": odoo_url,
            "ODOO_DB": odoo_db,
            "ODOO_USER": odoo_user,
            "ODOO_PASSWORD": odoo_password,
            "ODOO_YOLO": odoo_yolo,
        }
        self._request_id = 0
        self._tools = []
        self._proc = None

    # -- subprocess lifecycle ----------------------------------------------

    def _ensure_running(self):
        if self._proc and self._proc.poll() is None:
            return
        env = {**os.environ, **self._env_vars}
        self._proc = subprocess.Popen(
            ["uvx", "mcp-server-odoo"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        _logger.info("MCP server spawned (pid %s)", self._proc.pid)

    def is_alive(self):
        return self._proc is not None and self._proc.poll() is None

    # -- JSON-RPC over stdio -----------------------------------------------

    def _next_id(self):
        self._request_id += 1
        return self._request_id

    def _send(self, message):
        self._ensure_running()
        line = json.dumps(message, separators=(",", ":")) + "\n"
        self._proc.stdin.write(line.encode())
        self._proc.stdin.flush()

    def _read_response(self, expected_id):
        """Read lines until we get a JSON-RPC *response* with the matching id.

        Notifications (no ``id``) and other noise are silently skipped.
        """
        while True:
            raw = self._proc.stdout.readline()
            if not raw:
                # Process died — drain stderr to surface the real error
                stderr_output = ""
                try:
                    self._proc.wait(timeout=2)
                    stderr_output = (
                        (self._proc.stderr.read() or b"")
                        .decode(errors="replace")
                        .strip()
                    )
                except Exception:
                    pass
                _logger.error("MCP server died. stderr: %s", stderr_output or "(empty)")
                raise ConnectionError(
                    f"MCP server closed stdout (rc={self._proc.returncode}): {stderr_output or 'no stderr'}"
                )
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if msg.get("id") == expected_id:
                return msg
            # else: notification or unrelated — keep reading

    def _request(self, method, params=None):
        msg_id = self._next_id()
        self._send(
            {"jsonrpc": "2.0", "method": method, "params": params or {}, "id": msg_id}
        )
        return self._read_response(msg_id)

    def _notify(self, method, params=None):
        msg = {"jsonrpc": "2.0", "method": method}
        if params:
            msg["params"] = params
        self._send(msg)

    # -- public API --------------------------------------------------------

    def connect(self):
        """Initialize MCP session and cache tools."""
        self._ensure_running()

        self._request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "strat", "version": "0.1.0"},
            },
        )

        self._notify("notifications/initialized")

        result = self._request("tools/list", {})
        if result and "result" in result:
            self._tools = result["result"].get("tools", [])

        _logger.info("MCP session ready — %d tools discovered", len(self._tools))
        return self

    @property
    def tools(self):
        return self._tools

    def call_tool(self, name, arguments=None):
        """Call an MCP tool and return its text output."""
        result = self._request(
            "tools/call", {"name": name, "arguments": arguments or {}}
        )

        if result and "error" in result:
            return f"MCP error: {result['error'].get('message', result['error'])}"

        if result and "result" in result:
            content = result["result"].get("content", [])
            parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block["text"])
                elif isinstance(block, str):
                    parts.append(block)
            return "\n".join(parts) if parts else json.dumps(result["result"])

        return str(result)

    def stop(self):
        if self._proc:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None
