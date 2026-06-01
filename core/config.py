"""ClarkConfig — loads all configuration from clark.json.

No .env. No pydantic-settings. One JSON file, readable by humans and agents.
"""

import json
import logging
import os

logger = logging.getLogger(__name__)

_CONFIG_PATH = "clark.json"


class ClarkConfig:
    """Single-source config from clark.json.

    Usage:
        from core.config import settings
        settings.telegram_token     # "***"
        settings.telegram_chat_id   # loaded from clark.json
    """

    def __init__(self, path: str = _CONFIG_PATH):
        self._path = path
        self._raw: dict = {}
        self._load()

    def _load(self) -> None:
        """Load (or reload) config from the JSON file."""
        if not os.path.exists(self._path):
            logger.warning("Config file not found: %s — using defaults", self._path)
            self._raw = {}
        else:
            with open(self._path) as f:
                self._raw = json.load(f)

        # Core settings with defaults
        telegram = self._raw.get("telegram", {})
        self.telegram_token: str = telegram.get("token", "")
        self.telegram_chat_id: int = telegram.get("default_chat_id", 0)

        database = self._raw.get("database", {})
        self.db_path: str = database.get("path", "data/assistant.db")

        # Module configs (for module_manager to consume)
        self.module_configs: dict[str, dict] = self._raw.get("modules", {})

    def reload(self) -> None:
        """Hot-reload config from disk."""
        self._load()
        logger.info("Configuration reloaded from %s", self._path)

    def module_config(self, name: str) -> dict:
        """Get config for a specific module."""
        return self.module_configs.get(name, {})

    def module_enabled(self, name: str) -> bool:
        """Check if a module is enabled in config."""
        conf = self.module_configs.get(name, {})
        return conf.get("enabled", True)

    @property
    def enabled_plugins(self) -> list[str]:
        """Backward compat: list of enabled module names."""
        return [name for name, conf in self.module_configs.items()
                if conf.get("enabled", True)]


# Module-level singleton — import this everywhere
settings = ClarkConfig()
