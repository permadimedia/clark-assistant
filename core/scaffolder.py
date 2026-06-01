"""Module scaffolder — creates module directory, files, and updates clark.json.

Shared between CLI (cli.py) and API (POST /api/modules/scaffold).
"""

import json
import logging
import os
from pathlib import Path

from core.templates import (
    INIT_TEMPLATE,
    ROUTES_TEMPLATE,
    HANDLER_TEMPLATE,
    MIGRATION_TEMPLATE,
    make_context,
    render,
)

logger = logging.getLogger(__name__)

MODULES_DIR = "modules"
CONFIG_PATH = "clark.json"


def scaffold_module(
    name: str,
    description: str = "",
    with_handler: bool = False,
    with_migration: bool = False,
) -> dict:
    """Create a new module directory with boilerplate files.

    Returns a dict summary of what was created:
        {"name": str, "files": [str], "config_added": bool}
    """
    if not name or not name.isidentifier():
        raise ValueError(f"Invalid module name: '{name}'. Use a valid Python identifier.")

    module_dir = Path(MODULES_DIR) / name
    if module_dir.exists():
        raise FileExistsError(f"Module '{name}' already exists at {module_dir}")

    ctx = make_context(name, description)
    created_files = []

    # Create directory structure
    module_dir.mkdir(parents=True)

    # __init__.py
    init_content = render(INIT_TEMPLATE, ctx)
    (module_dir / "__init__.py").write_text(init_content)
    created_files.append(str(module_dir / "__init__.py"))

    # routes.py
    routes_content = render(ROUTES_TEMPLATE, ctx)
    (module_dir / "routes.py").write_text(routes_content)
    created_files.append(str(module_dir / "routes.py"))

    # handler.py (optional)
    if with_handler:
        handler_content = render(HANDLER_TEMPLATE, ctx)
        (module_dir / "handler.py").write_text(handler_content)
        created_files.append(str(module_dir / "handler.py"))

    # migrations/ (optional)
    if with_migration:
        migrations_dir = module_dir / "migrations"
        migrations_dir.mkdir()
        migration_content = render(MIGRATION_TEMPLATE, ctx)
        (migrations_dir / "001_initial.sql").write_text(migration_content)
        created_files.append(str(migrations_dir / "001_initial.sql"))

    # Update clark.json
    config_updated = _update_clark_json(name)

    logger.info("Scaffolded module '%s' — %d files created", name, len(created_files))

    return {
        "name": name,
        "files": created_files,
        "config_updated": config_updated,
    }


def _update_clark_json(name: str) -> bool:
    """Add module entry to clark.json modules section.

    Returns True if config was modified.
    """
    config_path = Path(CONFIG_PATH)
    if not config_path.exists():
        logger.warning("clark.json not found — skipping config update")
        return False

    with open(config_path) as f:
        config = json.load(f)

    modules = config.setdefault("modules", {})

    if name in modules:
        # Already exists — don't overwrite
        return False

    modules[name] = {"enabled": False}

    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")

    logger.info("Added '%s' to clark.json modules (disabled)", name)
    return True
