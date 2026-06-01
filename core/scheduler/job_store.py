"""JobStore — read/write cron_jobs + job_runs tables."""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from core.database import get_db

logger = logging.getLogger(__name__)


@dataclass
class CronJob:
    id: int
    name: str
    description: str
    job_type: str
    schedule_type: str
    schedule_config: dict[str, Any]
    payload: dict[str, Any]
    enabled: bool
    max_retries: int
    retry_delay_s: int
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    run_count: int = 0
    created_at: str = ""
    updated_at: str = ""

    @property
    def is_due(self, now: datetime | None = None) -> bool:
        if not self.enabled or self.next_run_at is None:
            return False
        return (now or datetime.now(timezone.utc)) >= self.next_run_at


@dataclass
class JobRun:
    id: int
    job_id: int
    status: str
    started_at: str
    finished_at: str | None = None
    error: str | None = None
    result: str | None = None
    attempt: int = 1


def _row_to_job(row: dict) -> CronJob:
    return CronJob(
        id=row["id"],
        name=row["name"],
        description=row["description"] or "",
        job_type=row["job_type"],
        schedule_type=row["schedule_type"],
        schedule_config=json.loads(row["schedule_config"]),
        payload=json.loads(row["payload"]),
        enabled=bool(row["enabled"]),
        max_retries=row["max_retries"],
        retry_delay_s=row["retry_delay_s"],
        last_run_at=_parse_dt(row["last_run_at"]),
        next_run_at=_parse_dt(row["next_run_at"]),
        run_count=row["run_count"],
        created_at=row["created_at"] or "",
        updated_at=row["updated_at"] or "",
    )


def _row_to_run(row: dict) -> JobRun:
    return JobRun(
        id=row["id"],
        job_id=row["job_id"],
        status=row["status"],
        started_at=row["started_at"] or "",
        finished_at=row["finished_at"],
        error=row["error"],
        result=row["result"],
        attempt=row["attempt"],
    )


def _parse_dt(val: str | None) -> datetime | None:
    if not val:
        return None
    try:
        if "T" in val:
            return datetime.fromisoformat(val)
        return datetime.strptime(val, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _fmt_dt(dt: datetime | None) -> str | None:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


class JobStore:
    """Persistent storage for cron jobs and run history."""

    # ── CRUD: cron_jobs ──────────────────────────────────────

    async def create_job(
        self,
        name: str,
        job_type: str,
        schedule_type: str,
        schedule_config: dict,
        payload: dict,
        description: str = "",
        enabled: bool = True,
        max_retries: int = 0,
        retry_delay_s: int = 60,
        next_run_at: datetime | None = None,
    ) -> int:
        db = await get_db()
        # Auto-compute next_run_at if not provided
        if next_run_at is None:
            next_run_at = self._compute_next_run(schedule_type, schedule_config)
        cursor = await db.execute(
            """INSERT INTO cron_jobs
               (name, description, job_type, schedule_type, schedule_config,
                payload, enabled, max_retries, retry_delay_s, next_run_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                name, description or "", job_type, schedule_type,
                json.dumps(schedule_config), json.dumps(payload),
                1 if enabled else 0, max_retries, retry_delay_s,
                _fmt_dt(next_run_at),
            ),
        )
        await db.commit()
        job_id = cursor.lastrowid
        logger.info("Job created: #%s '%s' (%s, %s)", job_id, name, job_type, schedule_type)
        return job_id

    async def get_job(self, job_id: int) -> CronJob | None:
        db = await get_db()
        cursor = await db.execute("SELECT * FROM cron_jobs WHERE id = ?", (job_id,))
        row = await cursor.fetchone()
        return _row_to_job(row) if row else None

    async def list_jobs(self, enabled_only: bool = False) -> list[CronJob]:
        db = await get_db()
        if enabled_only:
            cursor = await db.execute(
                "SELECT * FROM cron_jobs WHERE enabled = 1 ORDER BY next_run_at ASC"
            )
        else:
            cursor = await db.execute(
                "SELECT * FROM cron_jobs ORDER BY created_at DESC"
            )
        rows = await cursor.fetchall()
        return [_row_to_job(r) for r in rows]

    async def update_job(self, job_id: int, **kwargs) -> bool:
        """Update job fields. Keys: name, description, enabled, schedule_config, etc."""
        db = await get_db()
        sets = []
        values = []
        for key, val in kwargs.items():
            if key == "schedule_config":
                sets.append("schedule_config = ?")
                values.append(json.dumps(val))
                # Recompute next_run_at from DB
                existing = await self.get_job(job_id)
                if existing:
                    new_next = self._compute_next_run(existing.schedule_type, val)
                    sets.append("next_run_at = ?")
                    values.append(_fmt_dt(new_next))
            elif key == "payload":
                sets.append("payload = ?")
                values.append(json.dumps(val))
            elif key == "enabled":
                sets.append("enabled = ?")
                values.append(1 if val else 0)
            else:
                sets.append(f"{key} = ?")
                values.append(val)
        if not sets:
            return False
        sets.append("updated_at = ?")
        values.append(datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        values.append(job_id)
        cursor = await db.execute(
            f"UPDATE cron_jobs SET {', '.join(sets)} WHERE id = ?", values
        )
        await db.commit()
        return cursor.rowcount > 0

    async def delete_job(self, job_id: int) -> bool:
        db = await get_db()
        # Also clean up job runs
        await db.execute("DELETE FROM job_runs WHERE job_id = ?", (job_id,))
        cursor = await db.execute("DELETE FROM cron_jobs WHERE id = ?", (job_id,))
        await db.commit()
        return cursor.rowcount > 0

    async def set_enabled(self, job_id: int, enabled: bool) -> bool:
        return await self.update_job(job_id, enabled=enabled)

    # ── Scheduling queries ───────────────────────────────────

    async def get_next_due(self, now: datetime) -> CronJob | None:
        """Get the single next due job (for calculating sleep time)."""
        db = await get_db()
        cursor = await db.execute(
            "SELECT * FROM cron_jobs WHERE enabled = 1 ORDER BY next_run_at ASC LIMIT 1"
        )
        row = await cursor.fetchone()
        return _row_to_job(row) if row else None

    async def get_due_jobs(self, now: datetime) -> list[CronJob]:
        """Get all jobs that are due right now."""
        db = await get_db()
        now_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        cursor = await db.execute(
            "SELECT * FROM cron_jobs WHERE enabled = 1 AND next_run_at <= ? ORDER BY next_run_at ASC",
            (now_str,),
        )
        rows = await cursor.fetchall()
        return [_row_to_job(r) for r in rows]

    # ── Run tracking ─────────────────────────────────────────

    async def start_run(self, job_id: int, attempt: int = 1) -> int:
        db = await get_db()
        cursor = await db.execute(
            "INSERT INTO job_runs (job_id, status, attempt) VALUES (?, 'running', ?)",
            (job_id, attempt),
        )
        await db.commit()
        return cursor.lastrowid

    async def finish_run(self, run_id: int, status: str, error: str | None = None, result: str | None = None):
        db = await get_db()
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        await db.execute(
            "UPDATE job_runs SET status = ?, finished_at = ?, error = ?, result = ? WHERE id = ?",
            (status, now, error, result, run_id),
        )
        await db.commit()

    async def mark_next_run(self, job_id: int, next_run_at: datetime | None, run_count: int | None = None):
        """Update next_run_at and optionally increment run_count."""
        db = await get_db()
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if run_count is not None:
            await db.execute(
                "UPDATE cron_jobs SET last_run_at = ?, next_run_at = ?, run_count = ?, updated_at = ? WHERE id = ?",
                (now, _fmt_dt(next_run_at), run_count, now, job_id),
            )
        else:
            await db.execute(
                "UPDATE cron_jobs SET last_run_at = ?, next_run_at = ?, updated_at = ? WHERE id = ?",
                (now, _fmt_dt(next_run_at), now, job_id),
            )
        await db.commit()

    async def get_run_history(self, job_id: int, limit: int = 20) -> list[JobRun]:
        db = await get_db()
        cursor = await db.execute(
            "SELECT * FROM job_runs WHERE job_id = ? ORDER BY started_at DESC LIMIT ?",
            (job_id, limit),
        )
        rows = await cursor.fetchall()
        return [_row_to_run(r) for r in rows]

    async def get_stats(self) -> dict:
        db = await get_db()
        cursor = await db.execute("SELECT COUNT(*) as total, SUM(CASE WHEN enabled=1 THEN 1 ELSE 0 END) as active FROM cron_jobs")
        counts = await cursor.fetchone()
        cursor = await db.execute(
            "SELECT COUNT(*) as recent, SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) as success, SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) as failed FROM job_runs WHERE started_at >= datetime('now', '-1 day')"
        )
        runs = await cursor.fetchone()
        return {
            "total_jobs": counts["total"] or 0,
            "active_jobs": counts["active"] or 0,
            "runs_last_24h": runs["recent"] or 0,
            "success_last_24h": runs["success"] or 0,
            "failed_last_24h": runs["failed"] or 0,
        }

    # ── Helpers ──────────────────────────────────────────────

    @staticmethod
    def _compute_next_run(schedule_type: str, config: dict) -> datetime | None:
        """Compute next_run_at from a schedule config."""
        now = datetime.now(timezone.utc)
        if schedule_type == "once":
            at_str = config.get("at")
            if at_str:
                try:
                    dt = datetime.fromisoformat(at_str)
                    return dt.astimezone(timezone.utc)
                except Exception:
                    return None
            return None
        elif schedule_type == "interval":
            mins = config.get("interval_minutes", 5)
            return now
        elif schedule_type == "cron":
            # For initial creation, compute from cron config
            from croniter import croniter
            from zoneinfo import ZoneInfo
            tz_str = config.get("tz", "UTC")
            try:
                tz = ZoneInfo(tz_str)
            except Exception:
                tz = ZoneInfo("UTC")
            local_now = now.astimezone(tz)
            cron = croniter(config.get("cron", "* * * * *"), local_now)
            next_local = cron.get_next(datetime)
            return next_local.astimezone(timezone.utc)
        return None
