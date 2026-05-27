import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def read_env_value(key):
    """Read a value from the environment or the module's .env file."""
    val = os.getenv(key)
    if val:
        return val

    if not _ENV_PATH.exists():
        return None

    prefix = f"{key}="
    for line in _ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(prefix):
            return line[len(prefix) :].strip().strip('"').strip("'")
    return None


def write_env_value(key, value):
    """Write (or update) a single key=value pair in the module's .env file.

    Creates the file if it doesn't exist. Preserves existing entries.
    """
    if _ENV_PATH.exists():
        lines = _ENV_PATH.read_text().splitlines()
    else:
        lines = []

    prefix = f"{key}="
    found = False
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(prefix):
            new_lines.append(f"{key}={value}")
            found = True
        else:
            new_lines.append(line)

    if not found:
        new_lines.append(f"{key}={value}")

    _ENV_PATH.write_text("\n".join(new_lines) + "\n")
    logger.info("Wrote %s to %s", key, _ENV_PATH)


def save_odoo_config(username, password, url=None, database=None, yolo=None):
    """Save Odoo MCP connection settings to .env."""
    if username:
        write_env_value("ODOO_USER", username)
    if password:
        write_env_value("ODOO_PASSWORD", password)
    if url:
        write_env_value("ODOO_URL", url)
    if database:
        write_env_value("ODOO_DB", database)
    if yolo:
        write_env_value("ODOO_YOLO", yolo)


def get_api_key():
    key = read_env_value("ZAI_API_KEY")
    if not key:
        logger.error("ZAI_API_KEY not configured")
    return key


def get_odoo_config():
    """Read Odoo connection params from .env for the MCP server."""
    odoo_url = read_env_value("ODOO_URL")
    if not odoo_url:
        logger.debug("ODOO_URL not configured — agent mode disabled")
        return None
    return {
        "odoo_url": odoo_url,
        "odoo_db": read_env_value("ODOO_DB") or "",
        "odoo_user": read_env_value("ODOO_USER") or "admin",
        "odoo_password": read_env_value("ODOO_PASSWORD") or "admin",
        "odoo_yolo": read_env_value("ODOO_YOLO") or "read",
    }


def is_mcp_configured():
    """Check whether MCP credentials have been saved to .env."""
    return bool(read_env_value("ODOO_USER") and read_env_value("ODOO_PASSWORD"))
