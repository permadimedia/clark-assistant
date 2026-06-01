"""Plugin registry — manages lifecycle of all loaded plugins."""

import logging
from typing import Any

from core.plugin import Plugin

logger = logging.getLogger(__name__)


class PluginRegistry:
    """Singleton registry for all loaded plugins."""

    _instance: "PluginRegistry | None" = None

    def __init__(self) -> None:
        self._plugins: dict[str, Plugin] = {}

    @classmethod
    def get(cls) -> "PluginRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def register(self, plugin: Plugin) -> None:
        if not plugin.name:
            raise ValueError("Plugin must have a name")
        self._plugins[plugin.name] = plugin
        logger.info("Plugin registered: %s v%s — %s", plugin.name, plugin.version, plugin.description)

    def get_plugin(self, name: str) -> Plugin | None:
        return self._plugins.get(name)

    def all(self) -> list[Plugin]:
        return list(self._plugins.values())

    def names(self) -> list[str]:
        return list(self._plugins.keys())

    async def load_all(self, app: Any, names: list[str]) -> None:
        """Load plugins by name from the registry."""
        for name in names:
            plugin = self._plugins.get(name)
            if plugin:
                await plugin.on_load(app)
                logger.info("Plugin started: %s", name)
            else:
                logger.warning("Plugin '%s' not found, skipping", name)

    async def unload_all(self) -> None:
        """Unload all plugins."""
        for plugin in self._plugins.values():
            try:
                await plugin.on_unload()
            except Exception as e:
                logger.error("Error unloading plugin '%s': %s", plugin.name, e)

    async def health_all(self) -> dict:
        """Aggregate health from all plugins."""
        result = {}
        for name, plugin in self._plugins.items():
            try:
                result[name] = await plugin.on_health()
            except Exception as e:
                result[name] = {"error": str(e)}
        return result
