"""Scheduler module — manages SchedulerManager lifecycle + scheduler API."""

import logging

from core.module import Module
from core.scheduler import SchedulerManager

logger = logging.getLogger(__name__)


class SchedulerModule(Module):
    name = "scheduler"
    description = "Cron/interval/once job scheduler — manager + API"
    version = "0.2.0"
    routes = "modules.scheduler.routes"
    config_defaults = {
        "enabled": True,
    }

    def __init__(self):
        self._mgr: SchedulerManager | None = None

    @property
    def manager(self) -> SchedulerManager | None:
        return self._mgr

    async def on_load(self, app) -> None:
        """Create and start the SchedulerManager, then catch up past-due reminders."""
        from core.scheduler import SchedulerManager

        self._mgr = SchedulerManager()
        # Store on app state so API routes can access it
        app.state.scheduler_mgr = self._mgr
        await self._mgr.start()
        logger.info("Scheduler started")

        # Catch up past-due reminders that were missed while server was down
        recovered = await self._mgr.catch_up_past_due()
        if recovered:
            ok = sum(1 for r in recovered if r["recovered"])
            fail = len(recovered) - ok
            logger.info(
                "Startup catch-up: %d reminders recovered, %d failed",
                ok, fail,
            )
        else:
            logger.info("Startup catch-up: no past-due reminders found")

    async def on_unload(self) -> None:
        """Stop the SchedulerManager."""
        if self._mgr:
            await self._mgr.stop()
            self._mgr = None
        logger.info("Scheduler stopped")

    async def on_health(self) -> dict:
        return {
            "running": self._mgr.running if self._mgr else False,
        }
