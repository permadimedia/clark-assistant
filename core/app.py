"""App factory — creates and configures the FastAPI application.

Usage:
    from core.app import create_app
    app = create_app()
"""

import logging
from contextlib import asynccontextmanager

from pydantic import BaseModel
from fastapi import FastAPI, HTTPException


class _ScaffoldRequest(BaseModel):
    """Schema for POST /api/modules/scaffold body."""
    name: str
    description: str = ""
    with_handler: bool = False
    with_migration: bool = False

from core.config import settings
from core.database import init_db
from core.module_manager import ModuleManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Application lifespan — init DB, load modules, cleanup on shutdown."""
    # ── Database ──────────────────────────────────────────────
    await init_db()
    logger.info("Database initialized")

    # ── Module Manager ────────────────────────────────────────
    mgr = ModuleManager(app)

    # Load clark.json config overrides
    mgr.set_config_overrides(settings.module_configs)

    # Discover modules from modules/ directory
    mgr.discover("modules")

    # Register routes and job handlers
    mgr.register_routes()
    mgr.register_job_handlers()

    # Store for hot reload and health endpoints
    app.state.module_manager = mgr

    # Load enabled modules
    await mgr.load_all()
    logger.info("Modules active: %s", mgr.names())

    yield

    # ── Shutdown ──────────────────────────────────────────────
    await mgr.unload_all()
    logger.info("Shutdown complete")


def create_app() -> FastAPI:
    """Create and return a fully configured FastAPI application."""
    app = FastAPI(
        lifespan=_lifespan,
        title="clark",
        version="0.6.0",
        description="Ask clark. — AI agent backend API for menial tasks",
    )

    # ── Core health endpoints ─────────────────────────────────

    @app.get("/api/health")
    async def health():
        """Basic health check."""
        return {"status": "ok", "service": "clark", "version": "0.6.0"}

    @app.get("/api/health/detailed")
    async def health_detailed():
        """Detailed health check with module metrics."""
        mgr = getattr(app.state, "module_manager", None)
        if mgr is None:
            return {"status": "ok", "plugins": {}, "active_plugins": []}
        plugins_health = await mgr.health_all()
        return {
            "status": "ok",
            "plugins": plugins_health,
            "active_plugins": mgr.names(),
        }

    @app.get("/api/modules")
    async def list_modules():
        """List all registered modules."""
        mgr = getattr(app.state, "module_manager", None)
        if mgr is None:
            return []
        return [
            {
                "name": m.name,
                "description": m.description,
                "version": m.version,
                "config": m.config,
            }
            for m in mgr.all
        ]

    # ── Module scaffolding (for agents) ──────────────────────

    @app.post("/api/modules/scaffold")
    async def scaffold_module_endpoint(body: _ScaffoldRequest):
        """Create a new module with boilerplate files.

        Agent usage:
            curl -X POST /api/modules/scaffold \
              -H "Content-Type: application/json" \
              -d '{"name": "weather"}'
        """
        from core.scaffolder import scaffold_module as _scaffold

        try:
            result = _scaffold(
                name=body.name,
                description=body.description,
                with_handler=body.with_handler,
                with_migration=body.with_migration,
            )
        except (ValueError, FileExistsError) as e:
            raise HTTPException(status_code=400, detail=str(e))

        return {
            "status": "ok",
            "message": f"Module '{body.name}' created",
            "name": body.name,
            "files": result["files"],
            "config_updated": result["config_updated"],
            "next": "Edit files, enable in clark.json, then POST /api/reload",
        }

    # ── Hot reload ────────────────────────────────────────────

    @app.post("/api/reload")
    async def reload_config():
        """Hot-reload clark.json and reconfigure modules.

        Reads clark.json fresh, enables newly-enabled modules,
        disables newly-disabled modules, updates configs.
        Running jobs are NOT interrupted.
        """
        from core.config import settings as cfg

        cfg.reload()

        mgr = getattr(app.state, "module_manager", None)
        if mgr is None:
            return {"status": "ok", "message": "Config reloaded, modules pending"}

        # Update module config overrides from fresh config
        mgr.set_config_overrides(cfg.module_configs)

        # Reload config for each registered module
        reloaded = []
        for name in mgr.names():
            ok = await mgr.reload_module(name)
            if ok:
                reloaded.append(name)

        logger.info("Hot reload: %d modules refreshed", len(reloaded))
        return {
            "status": "ok",
            "message": "Configuration reloaded",
            "modules_reloaded": reloaded,
        }

    return app
