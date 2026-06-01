"""Plugin base class — all plugins inherit from this."""

import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class Plugin(ABC):
    """Base class for all plugins.

    Subclasses must set ``name`` and implement ``on_load`` + ``on_unload``.
    """

    name: str = ""
    description: str = ""
    version: str = "0.1.0"

    @abstractmethod
    async def on_load(self, app: Any) -> None:
        """Called when plugin is loaded — use for setup & background tasks."""
        ...

    async def on_unload(self) -> None:
        """Called during shutdown — use for cleanup."""
        pass

    async def on_health(self) -> dict:
        """Return health metrics for this plugin."""
        return {}
