"""Email automation module — organize, classify, and notify from your inbox.

Provider-agnostic: works with Gmail API, IMAP, and future providers.
Privacy-first: reads only metadata (from, subject, date, snippet).
"""

import logging

from core.module import Module

logger = logging.getLogger(__name__)


class EmailAutomationModule(Module):
    name = "email_automation"
    description = "Email inbox organizer — classify, label, notify via Telegram"
    version = "0.1.0"
    routes = "modules.email_automation.routes"
    config_defaults = {
        "enabled": False,
        "provider": "gmail",
        "credentials_path": "~/.config/email/credentials.json",
        "token_path": "~/.config/email/token.json",
        "scan_schedule": "0 7 * * *",
        "scan_limit": 50,
        "chat_id": 0,
        "labels_enabled": True,
        "archive_read_after_days": 90,
        "trash_draft_after_days": 30,
        "read_only": True,
    }
    job_handlers = {
        "email_daily_scan": "modules.email_automation.handler:handle_daily_scan",
    }

    def __init__(self):
        self._engine = None
        self._app = None

    @property
    def engine(self):
        return self._engine

    async def on_load(self, app) -> None:
        """Initialize email engine on module load."""
        from modules.email_automation.engine import EmailEngine

        self._app = app
        # Register module reference for handler/route access
        app.state.email_automation_module = self

        merged = self.config
        self._engine = EmailEngine(
            provider_type=merged.get("provider", "gmail"),
            credentials_path=merged.get("credentials_path", "~/.config/email/credentials.json"),
            token_path=merged.get("token_path", "~/.config/email/token.json"),
            scan_limit=merged.get("scan_limit", 50),
            read_only=merged.get("read_only", True),
        )
        logger.info("EmailAutomation module loaded (provider=%s, read_only=%s)", merged.get("provider"), merged.get("read_only"))

    async def on_unload(self) -> None:
        """Cleanup on module unload."""
        if self._engine:
            await self._engine.disconnect()
            self._engine = None
        logger.info("EmailAutomation module unloaded")

    async def on_health(self) -> dict:
        status = "disconnected"
        if self._engine and self._engine.provider:
            status = self._engine.provider.status
        return {
            "provider": self.config.get("provider", "unknown"),
            "status": status,
            "read_only": self.config.get("read_only", True),
            "last_scan": self._engine.last_scan_at if self._engine else None,
        }
