"""Daily email scan handler — triggered by Clark's Scheduler."""

import logging

from core.config import settings
from core.notifier import send_message
from core.scheduler.job_store import CronJob

logger = logging.getLogger(__name__)


async def handle_daily_scan(job: CronJob) -> str:
    """Daily inbox scan — fetch metadata, classify, and notify.

    Registered as job_type='email_daily_scan' in HANDLER_MAP.
    Triggered by Clark's Scheduler (default: 11:00 WIB daily).
    """
    try:
        # Resolve app state via scheduler's internal reference
        from core.scheduler import SchedulerManager

        app = getattr(job, "_app", None)
        if app is None:
            # Fallback: find running FastAPI instance
            import sys
            for mod_name, mod in sys.modules.items():
                if hasattr(mod, "app"):
                    candidate = getattr(mod, "app", None)
                    if candidate and "FastAPI" in type(candidate).__name__:
                        app = candidate
                        break

        if app is None or not hasattr(app, "state"):
            return "No FastAPI app reference available"

        module = getattr(app.state, "email_automation_module", None)
        if module is None:
            return "EmailAutomation module not loaded"

        engine = getattr(module, "engine", None)
        if engine is None:
            return "Email engine not initialized"

        # Run scan
        result = await engine.scan()
        summary = result.get("summary", "No emails processed.")

        # Send notification via Telegram
        chat_id = job.payload.get("chat_id", settings.telegram_chat_id)
        if summary:
            ok = await send_message(summary, chat_id=chat_id)
            if not ok:
                logger.warning("Daily scan: notification send failed")

        total = result.get("total", 0)
        priority = result.get("priority_count", 0)
        archived = result.get("archived_count", 0)

        logger.info(
            "Daily scan: %d processed, %d priority, %d archived",
            total, priority, archived,
        )
        return f"Daily scan: {total} processed, {priority} priority, {archived} archived"

    except Exception as e:
        logger.exception("Daily scan handler failed")
        return f"Daily scan failed: {e}"
