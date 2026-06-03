"""Daily email scan handler — triggered by Clark's Scheduler."""

import logging

from core.config import settings
from core.notifier import send_message
from core.scheduler.job_store import CronJob

logger = logging.getLogger(__name__)


async def handle_daily_scan(job: CronJob) -> str:
    """Daily inbox scan — fetch metadata, classify, label, and notify.

    Registered as job_type='email_daily_scan' in HANDLER_MAP.
    Triggered by Clark's Scheduler (default: 07:00 WIB daily).

    Returns a summary string for the scheduler job log.
    """
    # Resolve the email engine from the job's app context
    # (job has no direct app ref; we import the module manager lazily)
    try:
        from core.app import get_app, get_module_manager
        app = get_app()
        mgr = get_module_manager(app)
        module = mgr.get("email_automation") if mgr else None
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
