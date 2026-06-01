"""SchedulerManager — async job scheduler with cron/interval/once support.

Controls the main scheduling loop: sleeps precisely until the next due job,
executes it, updates its next run time, and logs results.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from core.scheduler.handlers import get_handler
from core.scheduler.job_store import CronJob, JobStore

logger = logging.getLogger(__name__)

# Fallback poll if no jobs exist — 5 minutes (human-like rhythm)
# Past-due catch-up handles reminders missed during downtime.
NO_JOB_POLL_S = 300


class SchedulerManager:
    """Orchestrates job execution. One instance per app.

    Usage:
        mgr = SchedulerManager()
        await mgr.start()   # kicks off background loop
        await mgr.stop()    # cancels loop
    """

    def __init__(self):
        self._task: asyncio.Task | None = None
        self._store = JobStore()

    @property
    def store(self) -> JobStore:
        return self._store

    async def start(self):
        if self._task and not self._task.done():
            logger.warning("Scheduler already running")
            return
        self._task = asyncio.create_task(self._run_loop())
        logger.info("SchedulerManager started")

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
            logger.info("SchedulerManager stopped")

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    # ── Main loop ────────────────────────────────────────────

    async def _run_loop(self):
        """Main scheduler loop — runs forever until cancelled."""
        try:
            while True:
                await self._tick()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.exception("Scheduler loop crashed: %s", e)

    async def _tick(self):
        """One iteration: calculate sleep, execute due jobs, repeat."""
        now = datetime.now(timezone.utc)
        next_job = await self._store.get_next_due(now)

        if next_job and next_job.next_run_at:
            sleep_seconds = (next_job.next_run_at - now).total_seconds()
            if sleep_seconds > 0:
                await asyncio.sleep(sleep_seconds)

            # Wake — fetch ALL jobs due now
            due_jobs = await self._store.get_due_jobs(datetime.now(timezone.utc))
            for job in due_jobs:
                await self._execute_job(job)
        else:
            # No jobs — sleep and retry
            await asyncio.sleep(NO_JOB_POLL_S)

    # ── Job execution ────────────────────────────────────────

    async def _execute_job(self, job: CronJob):
        """Execute a single job with retry support and run tracking."""
        attempt = 0
        max_attempts = 1 + max(0, job.max_retries)

        while attempt < max_attempts:
            attempt += 1
            run_id = await self._store.start_run(job.id, attempt)

            try:
                handler = get_handler(job.job_type)
                if handler is None:
                    raise RuntimeError(f"No handler for job_type '{job.job_type}'")

                result = await handler(job)
                await self._store.finish_run(run_id, "success", result=result)

                logger.info("Job #%d '%s' OK: %s", job.id, job.name, result)
                break  # success

            except Exception as e:
                error_msg = f"{type(e).__name__}: {e}"
                logger.warning(
                    "Job #%d '%s' failed (attempt %d/%d): %s",
                    job.id, job.name, attempt, max_attempts, error_msg,
                )

                if attempt < max_attempts:
                    # Retry after delay
                    await self._store.finish_run(run_id, "failed", error=error_msg)
                    await asyncio.sleep(job.retry_delay_s)
                else:
                    await self._store.finish_run(run_id, "failed", error=error_msg)
                    logger.error("Job #%d '%s' exhausted retries", job.id, job.name)

        # Update next run time regardless
        next_run = self._compute_next_run(job)
        await self._store.mark_next_run(job.id, next_run, run_count=job.run_count + 1)

        # Auto-disable once-type jobs after first run
        if job.schedule_type == "once" or next_run is None:
            await self._store.set_enabled(job.id, False)

    # ── Past-due catch-up ────────────────────────────────────

    async def catch_up_past_due(self) -> list[dict]:
        """Scan for past-due unfired reminders and fire them.

        Runs on scheduler startup so reminders aren't lost if
        the server was down when they were due.

        Returns a list of dicts: {id, text, recovered}
        """
        from core.config import settings
        from core.database import get_db
        from core.notifier import send_message

        USER_CHAT_ID = settings.telegram_chat_id
        WIB = timezone(timedelta(hours=7))

        db = await get_db()
        now_utc = datetime.now(timezone.utc)

        cursor = await db.execute(
            "SELECT id, text, remind_at, chat_id FROM reminders "
            "WHERE fired = 0 AND remind_at <= ?",
            (now_utc.strftime("%Y-%m-%d %H:%M:%S"),),
        )
        rows = await cursor.fetchall()

        if not rows:
            logger.info("Catch-up: no past-due reminders to recover")
            return []

        recovered = []
        for row in rows:
            rid = row["id"]
            text = row["text"]
            raw_time = row["remind_at"]
            chat_id = row["chat_id"] or USER_CHAT_ID

            # Format time for display
            try:
                dt = datetime.fromisoformat(raw_time) if "T" in raw_time \
                    else datetime.strptime(raw_time, "%Y-%m-%d %H:%M:%S")
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                local = dt.astimezone(WIB)
                time_str = local.strftime("%H:%M")
            except Exception:
                time_str = raw_time

            # Format: first line as title (bold), rest as details (normal)
            split = text.split("\n", 1)
            title = split[0]
            details = split[1] if len(split) > 1 else ""

            if details:
                message = (
                    f"🔔 <b>{title}</b>\n"
                    f"{details}\n\n"
                    f"⏰ {time_str} (terlewat — server mati)\n"
                    f"━━━━━━━━━━━━━━━━\n"
                    f"🦊 <i>clark</i>"
                )
            else:
                message = (
                    f"🔔 <b>{text}</b>\n\n"
                    f"⏰ {time_str} (terlewat — server mati)\n"
                    f"━━━━━━━━━━━━━━━━\n"
                    f"🦊 <i>clark</i>"
                )

            try:
                ok = await send_message(message, chat_id=chat_id)
                if ok:
                    await db.execute(
                        "UPDATE reminders SET fired = 1 WHERE id = ?",
                        (rid,),
                    )
                    await db.commit()
                    logger.info(
                        "Catch-up: recovered reminder #%d '%s' (due %s)",
                        rid, text[:40], time_str,
                    )
                    recovered.append({
                        "id": rid,
                        "text": text,
                        "recovered": True,
                    })
                else:
                    logger.warning(
                        "Catch-up: reminder #%d send failed (telegram)", rid,
                    )
                    recovered.append({
                        "id": rid,
                        "text": text,
                        "recovered": False,
                        "error": "send_message failed",
                    })
            except Exception as e:
                logger.exception(
                    "Catch-up: reminder #%d error: %s", rid, e,
                )
                recovered.append({
                    "id": rid,
                    "text": text,
                    "recovered": False,
                    "error": str(e),
                })

        total_ok = sum(1 for r in recovered if r["recovered"])
        total_fail = len(recovered) - total_ok
        logger.info(
            "Catch-up done: %d recovered, %d failed out of %d past-due",
            total_ok, total_fail, len(recovered),
        )
        return recovered

    # ── Schedule computation ────────────────────────────────

    @staticmethod
    def _compute_next_run(job: CronJob) -> datetime | None:
        """Compute the next scheduled run after this execution."""
        now = datetime.now(timezone.utc)

        if job.schedule_type == "once":
            # One-shot — disable after firing
            return None  # mark_next_run will set None; caller disables

        elif job.schedule_type == "interval":
            mins = job.schedule_config.get("interval_minutes", 5)
            return now + timedelta(minutes=mins)

        elif job.schedule_type == "cron":
            from croniter import croniter
            from zoneinfo import ZoneInfo
            tz_str = job.schedule_config.get("tz", "UTC")
            try:
                tz = ZoneInfo(tz_str)
            except Exception:
                tz = ZoneInfo("UTC")
            local_now = now.astimezone(tz)
            cron = croniter(job.schedule_config.get("cron", "* * * * *"), local_now)
            try:
                next_local = cron.get_next(datetime)
                return next_local.astimezone(timezone.utc)
            except Exception:
                return None

        return None

    # ── Manual trigger ───────────────────────────────────────

    async def trigger_job(self, job_id: int) -> str:
        """Manually trigger a job immediately. Returns result string."""
        job = await self._store.get_job(job_id)
        if not job:
            raise ValueError(f"Job #{job_id} not found")

        handler = get_handler(job.job_type)
        if handler is None:
            raise RuntimeError(f"No handler for job_type '{job.job_type}'")

        # Execute with full run tracking (like normal tick, but with 0 retries)
        run_id = await self._store.start_run(job.id, attempt=1)
        try:
            result = await handler(job)
            await self._store.finish_run(run_id, "success", result=result)
        except Exception as e:
            error_msg = f"{type(e).__name__}: {e}"
            await self._store.finish_run(run_id, "failed", error=error_msg)
            raise

        # Update next_run normally
        next_run = self._compute_next_run(job)
        await self._store.mark_next_run(job.id, next_run, run_count=job.run_count + 1)

        # Auto-disable once-type
        if job.schedule_type == "once" or next_run is None:
            await self._store.set_enabled(job.id, False)

        return result
