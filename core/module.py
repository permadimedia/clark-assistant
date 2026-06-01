"""Module base class — all modules inherit from this.

A module is a self-contained feature folder. It declares its routes,
job handlers, config defaults, and lifecycle hooks — the framework
wires everything automatically.
"""

import logging
from abc import ABC
from typing import Any, Callable

logger = logging.getLogger(__name__)


class Module(ABC):
    """Declarative module base class.

    Subclasses set class-level fields to declare what the module provides.
    The ModuleManager reads these fields at startup to auto-wire routes,
    job handlers, and config.

    Usage:
        class WeatherModule(Module):
            name = "weather"
            description = "Daily weather forecast"
            version = "0.1.0"
            routes = "modules.weather.routes"
            job_handlers = {"forecast": "modules.weather.handler:handle"}
            config_defaults = {"enabled": False, "city": "Jakarta"}
    """

    # ── Declaration fields ───────────────────────────────────
    name: str = ""
    description: str = ""
    version: str = "0.1.0"

    # Dot-path to routes module (must expose `router` APIRouter)
    routes: str | None = None

    # {job_type: "dot.path.to:handler_func"}
    job_handlers: dict[str, str] = {}

    # Default config values (merged with clark.json overrides)
    config_defaults: dict[str, Any] = {}

    # Relative paths to migration SQL files (inside module dir)
    migrations: list[str] = []

    # ── Module state (set by framework) ──────────────────────
    config: dict[str, Any] = {}

    # ── Lifecycle hooks ──────────────────────────────────────
    async def on_load(self, app) -> None:
        """Called when module is enabled (on startup or hot reload)."""
        pass

    async def on_unload(self) -> None:
        """Called when module is disabled or app shuts down."""
        pass

    async def on_health(self) -> dict:
        """Return health metrics for this module."""
        return {}
