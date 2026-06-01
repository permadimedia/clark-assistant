"""ModuleManager — discovers, registers, and manages module lifecycle.

Scans modules/*/ for Module subclasses, wires routes and job handlers,
merges config with clark.json, and manages startup/shutdown lifecycle.
"""

import importlib
import logging
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from core.module import Module

logger = logging.getLogger(__name__)


class ModuleManager:
    """Orchestrates module discovery, registration, and lifecycle.

    Usage:
        mgr = ModuleManager(app)
        mgr.discover("modules")          # scan directory
        mgr.register_routes()            # wire API routers
        mgr.register_job_handlers()      # wire scheduler handlers
        await mgr.load_all()             # call on_load for enabled modules
        await mgr.unload_all()           # call on_unload on shutdown
    """

    def __init__(self, app: FastAPI):
        self.app = app
        self._modules: dict[str, Module] = {}
        self._config_overrides: dict[str, dict] = {}

    # ── Discovery ────────────────────────────────────────────

    def discover(self, *directories: str) -> None:
        """Scan directories for module declarations (*/__init__.py)."""
        for directory in directories:
            path = Path(directory)
            if not path.is_dir():
                logger.warning("Module directory not found: %s", path)
                continue

            for entry in sorted(path.iterdir()):
                if not entry.is_dir():
                    continue
                init_file = entry / "__init__.py"
                if not init_file.exists():
                    continue

                module_name = entry.name
                try:
                    # Import the __init__.py to find Module subclasses
                    spec = importlib.util.spec_from_file_location(
                        f"modules.{module_name}",
                        str(init_file),
                    )
                    if spec is None or spec.loader is None:
                        continue

                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)

                    # Find Module subclasses in this module
                    for attr_name in dir(mod):
                        attr = getattr(mod, attr_name)
                        if isinstance(attr, type) and issubclass(attr, Module) and attr is not Module:
                            instance = attr()
                            self._register(instance)
                            break  # one module class per package

                except Exception as e:
                    logger.error("Failed to load module '%s': %s", module_name, e)

    def _register(self, module: Module) -> None:
        """Register a single module instance."""
        if not module.name:
            logger.warning("Skipping unnamed module")
            return
        self._modules[module.name] = module
        logger.info(
            "Module registered: %s v%s — %s",
            module.name, module.version, module.description,
        )

    # ── Registration ─────────────────────────────────────────

    def register_routes(self) -> None:
        """Import and register each module's API router."""
        for name, module in self._modules.items():
            if not module.routes:
                continue
            try:
                # Import the routes module
                routes_mod = importlib.import_module(module.routes)
                router = getattr(routes_mod, "router", None)
                if router is None:
                    logger.warning(
                        "Module '%s' has routes='%s' but no 'router' found",
                        name, module.routes,
                    )
                    continue
                self.app.include_router(router)
                logger.debug("Module '%s': routes registered", name)
            except Exception as e:
                logger.error("Module '%s': failed to register routes: %s", name, e)

    def register_job_handlers(self) -> None:
        """Register job handlers into core/scheduler's job registry."""
        # This is done lazily via the handler resolution system
        # Currently core/scheduler/handlers.py uses HANDLER_MAP
        # Future: dynamic registration through JobRegistry class
        from core.scheduler.handlers import HANDLER_MAP

        for name, module in self._modules.items():
            for job_type, handler_path in module.job_handlers.items():
                try:
                    module_path, func_name = handler_path.split(":")
                    handler_mod = importlib.import_module(module_path)
                    handler_func = getattr(handler_mod, func_name)
                    HANDLER_MAP[job_type] = handler_func
                    logger.debug(
                        "Module '%s': handler '%s' → '%s'", name, job_type, handler_path,
                    )
                except Exception as e:
                    logger.error(
                        "Module '%s': failed to register handler '%s': %s",
                        name, handler_path, e,
                    )

    # ── Config merging ──────────────────────────────────────

    def set_config_overrides(self, overrides: dict[str, dict]) -> None:
        """Set clark.json overrides for each module."""
        self._config_overrides = overrides

    def _merged_config(self, module: Module) -> dict:
        """Merge module defaults with clark.json overrides."""
        merged = dict(module.config_defaults)
        overrides = self._config_overrides.get(module.name, {})
        merged.update(overrides)
        return merged

    # ── Lifecycle ────────────────────────────────────────────

    async def load_all(self) -> None:
        """Call on_load for all enabled modules."""
        for name, module in self._modules.items():
            merged_config = self._merged_config(module)
            module.config = merged_config

            enabled = merged_config.get("enabled", True)
            if not enabled:
                logger.info("Module '%s': skipped (disabled)", name)
                continue

            try:
                await module.on_load(self.app)
                logger.info("Module started: %s", name)
            except Exception as e:
                logger.error("Module '%s': on_load failed: %s", name, e)

    async def unload_all(self) -> None:
        """Call on_unload for all modules (shutdown)."""
        for module in self._modules.values():
            try:
                await module.on_unload()
            except Exception as e:
                logger.error(
                    "Module '%s': on_unload error: %s", module.name, e,
                )

    async def reload_module(self, name: str) -> bool:
        """Hot-reload a single module's config and lifecycle."""
        module = self._modules.get(name)
        if module is None:
            return False

        merged_config = self._merged_config(module)
        old_config = module.config
        module.config = merged_config

        old_enabled = old_config.get("enabled", True)
        new_enabled = merged_config.get("enabled", True)

        if old_enabled and not new_enabled:
            # Disable
            await module.on_unload()
            logger.info("Module disabled: %s", name)
        elif not old_enabled and new_enabled:
            # Enable
            try:
                await module.on_load(self.app)
                logger.info("Module enabled: %s", name)
            except Exception as e:
                logger.error("Module '%s': on_load failed on reload: %s", name, e)
        # else: config changed but enabled state same — up to module to react

        return True

    async def health_all(self) -> dict:
        """Aggregate health from all modules."""
        result = {}
        for name, module in self._modules.items():
            try:
                result[name] = await module.on_health()
            except Exception as e:
                result[name] = {"error": str(e)}
        return result

    # ── Queries ──────────────────────────────────────────────

    @property
    def all(self) -> list[Module]:
        return list(self._modules.values())

    def get(self, name: str) -> Module | None:
        return self._modules.get(name)

    def names(self) -> list[str]:
        return list(self._modules.keys())