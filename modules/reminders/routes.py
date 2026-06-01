"""Reminder CRUD API endpoints."""

import json
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from core.config import settings
from core.database import get_db

router = APIRouter(prefix="/api/reminders", tags=["reminders"])

logger = logging.getLogger(__name__)

USER_CHAT_ID = settings.telegram_chat_id


# ── Pydantic models ────────────────────────────────────────

class ReminderCreate(BaseModel):
    text: str
    time: str  # ISO 8601, e.g. "2026-06-01T14:00:00+07:00"
    chat_id: int = 0
    user_id: int = 0
    alert_before_minutes: int = Field(
        default=10,
        description="Minutes before event to send the reminder. Default 10.",
        ge=0,
    )


class ReminderResponse(BaseModel):
    id: int
    text: str
    time: str
    chat_id: int
    fired: bool
    created_at: str | None = None
    alert_before_minutes: int = 10


# ── Endpoints ──────────────────────────────────────────────

@router.post("", response_model=ReminderResponse)
async def create_reminder(body: ReminderCreate, request: Request):
    """Create a new reminder.

    Automatically creates a scheduler job that fires
    `alert_before_minutes` before the event time.

    Example:
        Event at 14:00, alert_before_minutes=10
        → Notification at 13:50
        → Body shows "⏰ 14:00"
    """
    try:
        event_at = datetime.fromisoformat(body.time)
        if event_at.tzinfo is None:
            raise ValueError("Time must include timezone")
        event_at = event_at.astimezone(timezone.utc)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid time: {e}")

    # Compute alert time
    alert_delta = timedelta(minutes=body.alert_before_minutes)
    alert_at = event_at - alert_delta

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    chat_id = body.chat_id if body.chat_id else USER_CHAT_ID
    user_id = body.user_id if body.user_id else chat_id

    db = await get_db()

    # Store alert_before_minutes in the alerts JSON field
    alerts_json = json.dumps([body.alert_before_minutes])

    c = await db.execute(
        "INSERT INTO reminders (chat_id, user_id, text, remind_at, alerts, source_text) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (chat_id, user_id, body.text, event_at.strftime("%Y-%m-%d %H:%M:%S"), alerts_json, ""),
    )
    rid = c.lastrowid
    await db.commit()

    # Auto-create a scheduler job for this reminder
    scheduler_mgr = getattr(request.app.state, "scheduler_mgr", None)
    if scheduler_mgr is not None:
        # Only schedule if alert time is in the future
        now_utc = datetime.now(timezone.utc)
        if alert_at > now_utc:
            job_id = await scheduler_mgr.store.create_job(
                name=f"Reminder #{rid}",
                description=f"Alert for: {body.text[:50]}",
                job_type="reminder_alert",
                schedule_type="once",
                schedule_config={"at": alert_at.isoformat()},
                payload={"reminder_id": rid, "chat_id": chat_id},
                enabled=True,
            )
            logger.info(
                "Reminder #%d: alert at %s (%d min before event), job #%d",
                rid, alert_at.strftime("%Y-%m-%d %H:%M UTC"),
                body.alert_before_minutes, job_id,
            )
        else:
            # Alert time already passed — fire immediately via catch-up
            logger.info(
                "Reminder #%d: alert time %s already past, queued for catch-up",
                rid, alert_at.strftime("%Y-%m-%d %H:%M UTC"),
            )
    else:
        logger.warning("Reminder #%d: no scheduler available (scheduler module not loaded?)", rid)

    return ReminderResponse(
        id=rid,
        text=body.text,
        time=event_at.isoformat(),
        chat_id=chat_id,
        fired=False,
        created_at=now_str,
        alert_before_minutes=body.alert_before_minutes,
    )


@router.get("", response_model=list[ReminderResponse])
async def list_reminders(fired: bool = False):
    """List active reminders."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT id, text, remind_at, chat_id, fired, alerts FROM reminders "
        "WHERE chat_id = ? AND fired = ? ORDER BY remind_at ASC",
        (USER_CHAT_ID, int(fired)),
    )
    rows = await cursor.fetchall()
    return [_row_to_response(r) for r in rows]


@router.get("/{reminder_id}", response_model=ReminderResponse)
async def get_reminder(reminder_id: int):
    """Get a single reminder by ID."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT id, text, remind_at, chat_id, fired, alerts FROM reminders "
        "WHERE id = ? AND chat_id = ?",
        (reminder_id, USER_CHAT_ID),
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Reminder not found")
    return _row_to_response(row)


@router.delete("/{reminder_id}")
async def delete_reminder(reminder_id: int, request: Request):
    """Cancel/delete a reminder and disable its scheduler job."""
    db = await get_db()
    cursor = await db.execute(
        "DELETE FROM reminders WHERE id = ? AND chat_id = ?",
        (reminder_id, USER_CHAT_ID),
    )
    await db.commit()
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Reminder not found")

    # Also disable associated scheduler job
    scheduler_mgr = getattr(request.app.state, "scheduler_mgr", None)
    if scheduler_mgr is not None:
        jobs = await scheduler_mgr.store.list_jobs()
        for job in jobs:
            if job.payload.get("reminder_id") == reminder_id:
                await scheduler_mgr.store.set_enabled(job.id, False)
                logger.info("Reminder #%d: disabled scheduler job #%d", reminder_id, job.id)
                break

    logger.info("Reminder #%d deleted", reminder_id)
    return {"status": "deleted", "id": reminder_id}


@router.post("/{reminder_id}/done")
async def mark_done(reminder_id: int):
    """Mark a reminder as done/fired."""
    db = await get_db()
    cursor = await db.execute(
        "UPDATE reminders SET fired = 1 WHERE id = ? AND chat_id = ? AND fired = 0",
        (reminder_id, USER_CHAT_ID),
    )
    await db.commit()
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Reminder not found or already done")
    return {"status": "done", "id": reminder_id}


# ── Helpers ────────────────────────────────────────────────

def _row_to_response(row) -> ReminderResponse:
    """Convert a database row to a ReminderResponse."""
    alerts_str = row["alerts"] or "[]"
    try:
        alerts = json.loads(alerts_str)
        alert_before = alerts[0] if alerts else 10
    except (json.JSONDecodeError, IndexError):
        alert_before = 10

    return ReminderResponse(
        id=row["id"],
        text=row["text"],
        time=row["remind_at"],
        chat_id=row["chat_id"],
        fired=bool(row["fired"]),
        alert_before_minutes=alert_before,
    )
