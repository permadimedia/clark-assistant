"""Module scaffolding templates — used by CLI and API.

Templates use Python {variable} substitution.
No Jinja2 needed — stdlib string.Template or str.format works.
"""

# ── Module declaration ──────────────────────────────────────

INIT_TEMPLATE = '''\
"""{{name}} module — {{description}}."""

from core.module import Module


class {{PascalName}}Module(Module):
    name = "{{name}}"
    description = "{{description}}"
    version = "0.1.0"
    routes = "modules.{{name}}.routes"
    config_defaults = {
        "enabled": False,
    }
'''

# ── API routes ──────────────────────────────────────────────

ROUTES_TEMPLATE = '''\
"""{{name}} API endpoints."""

from fastapi import APIRouter
from pydantic import BaseModel
from core.database import get_db

router = APIRouter(prefix="/api/{{name}}", tags=["{{name}}"])


# ── Models ──────────────────────────────────────────────────

class {{PascalName}}Item(BaseModel):
    id: int
    text: str


# ── Endpoints ───────────────────────────────────────────────

@router.get("")
async def list_{{name}}():
    """List all {{name}} items."""
    return {"items": []}


@router.post("")
async def create_{{name}}(body: {{PascalName}}Item):
    """Create a {{name}} item."""
    return {"status": "created", "item": body}
'''

# ── Job handler (optional, for scheduled tasks) ────────────

HANDLER_TEMPLATE = '''\
"""{{name}} job handlers."""

from core.notifier import send_message


async def handle_{{name}}_task(job):
    """Process a {{name}} scheduled task."""
    chat_id = job.payload.get("chat_id", 0)
    result = f"{{name}} task completed"
    return result
'''

# ── Migration SQL template (optional) ──────────────────────

MIGRATION_TEMPLATE = '''\
-- {{name}} module migration
-- Created at: {{timestamp}}

CREATE TABLE IF NOT EXISTS {{name}}_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
'''


def render(template: str, variables: dict) -> str:
    """Render a template with the given variables.

    Uses simple {{var}} substitution with str.replace.
    Supports PascalName conversion: "weather" -> "Weather".
    """
    result = template
    for key, val in variables.items():
        result = result.replace("{{" + key + "}}", str(val))
    return result


def make_context(name: str, description: str = "") -> dict:
    """Build template context from module name."""
    if not description:
        description = name.title()
    return {
        "name": name,
        "PascalName": name.title().replace("_", ""),
        "description": description,
        "timestamp": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
