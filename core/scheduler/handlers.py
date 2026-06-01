"""Job handlers — map job_type → execution logic."""

import logging
from datetime import datetime, timedelta, timezone

from core.config import settings
from core.database import get_db
from core.notifier import send_message
from core.scheduler.job_store import CronJob

logger = logging.getLogger(__name__)

WIB = timezone(timedelta(hours=7))
USER_CHAT_ID = settings.telegram_chat_id


async def handle_send_message(job: CronJob) -> str:
    """Send an arbitrary Telegram message."""
    payload = job.payload
    text = payload.get("text", "")
    chat_id = payload.get("chat_id", USER_CHAT_ID)
    parse_mode = payload.get("parse_mode", "HTML")

    if not text:
        return "No text in payload"

    ok = await send_message(text, chat_id=chat_id, parse_mode=parse_mode)
    if ok:
        logger.info("send_message job #%s sent to %s", job.id, chat_id)
        return f"Message sent to {chat_id}"
    else:
        raise RuntimeError(f"Failed to send message to {chat_id}")


async def handle_send_agenda(job: CronJob) -> str:
    """Query agenda and send formatted summary via Telegram."""
    payload = job.payload
    chat_id = payload.get("chat_id", USER_CHAT_ID)
    date_range = payload.get("range", "today")

    # Determine which date to query
    now_wib = datetime.now(WIB)
    if date_range == "today":
        date_str = now_wib.strftime("%Y-%m-%d")
        label = "HARI INI"
        day_name = _day_name(now_wib)
    elif date_range == "tomorrow":
        target = now_wib + timedelta(days=1)
        date_str = target.strftime("%Y-%m-%d")
        label = "BESOK"
        day_name = _day_name(target)
    else:
        date_str = date_range
        label = date_range
        day_name = ""

    # Query reminders for that date (reusing same query as agenda API)
    items = await _query_agenda_items(chat_id, date_str)

    # Format message
    if not items:
        header = f"📋 <b>Agenda {label}</b>"
        if day_name:
            header += f" — {day_name}, {date_str}"
        header += "\n\nTidak ada jadwal."
        text = header + "\n\nSantai aja 😎"
    else:
        header = f"📋 <b>AGENDA {label}</b>"
        if day_name:
            header += f" — {day_name}"
        header += "\n" + "─" * 25 + "\n"

        lines = []
        for item in items:
            time_str = item["time"]
            title = item["text"]
            done_mark = " ✅" if item["done"] else ""
            lines.append(f"\n⏰ <b>{time_str}</b>{done_mark}")
            lines.append(f"   {title}")

        done_count = sum(1 for it in items if it["done"])
        total = len(items)
        footer = (
            f"\n\n{'─' * 25}"
            f"\n{total} agenda · {done_count} selesai "
            f"{'· 🎉 semua beres!' if done_count == total else '💪 semangat!'}"
        )

        text = header + "\n".join(lines) + footer

    ok = await send_message(text, chat_id=chat_id)
    if ok:
        logger.info("send_agenda job #%s sent (%s, %d items)", job.id, date_range, len(items))
        return f"Agenda {date_range}: {len(items)} items sent"
    else:
        raise RuntimeError(f"Failed to send agenda to {chat_id}")


async def handle_reminder_alert(job: CronJob) -> str:
    """Fire a single reminder notification.

    This replaces the old polling logic for individual reminders.
    The old scheduler plugin is being replaced, but we keep backward compat
    by allowing direct reminder-alert jobs.
    """
    payload = job.payload
    reminder_id = payload.get("reminder_id")
    if not reminder_id:
        raise RuntimeError("reminder_alert job missing reminder_id in payload")

    db = await get_db()
    cursor = await db.execute(
        "SELECT id, text, remind_at, chat_id FROM reminders WHERE id = ? AND fired = 0",
        (reminder_id,),
    )
    row = await cursor.fetchone()
    if not row:
        return f"Reminder #{reminder_id} already fired or not found"

    text = row["text"]
    raw_time = row["remind_at"]
    chat_id = row["chat_id"] or USER_CHAT_ID

    # Format time + short date for display
    try:
        dt = datetime.fromisoformat(raw_time) if "T" in raw_time else datetime.strptime(raw_time, "%Y-%m-%d %H:%M:%S")
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        local = dt.astimezone(WIB)
        time_str = local.strftime("%H:%M")
        date_str = local.strftime("%-d %b")  # e.g. "1 Jun"
    except Exception:
        time_str = raw_time
        date_str = ""

    # Format: first line as title with [time, date] prefix, rest as details
    lines = text.split("\n", 1)
    title = lines[0]
    details = lines[1] if len(lines) > 1 else ""

    tag = f"[{time_str}, {date_str}] "

    if details:
        message = (
            f"🔔 <b>{tag}{title}</b>\n"
            f"{details}\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"🦊 <i>clark</i>"
        )
    else:
        message = (
            f"🔔 <b>{tag}{text}</b>\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"🦊 <i>clark</i>"
        )

    ok = await send_message(message, chat_id=chat_id)
    if ok:
        await db.execute("UPDATE reminders SET fired = 1 WHERE id = ?", (reminder_id,))
        await db.commit()
        logger.info("Reminder #%d fired via scheduler job", reminder_id)
        return f"Reminder #{reminder_id} fired"
    else:
        raise RuntimeError(f"Failed to send reminder #{reminder_id}")


# ── Internal helpers ──────────────────────────────────────

async def _query_agenda_items(chat_id: int, date_str: str) -> list[dict]:
    """Get agenda items for a date (same query as agenda API)."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT id, text, remind_at, fired FROM reminders "
        "WHERE chat_id = ? AND DATE(remind_at) = ? "
        "ORDER BY remind_at ASC",
        (chat_id, date_str),
    )
    rows = await cursor.fetchall()
    result = []
    for r in rows:
        dt = datetime.fromisoformat(r["remind_at"])
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        local = dt.astimezone(WIB)
        result.append({
            "id": r["id"],
            "text": r["text"],
            "time": local.strftime("%H:%M"),
            "done": bool(r["fired"]),
        })
    return result


def _day_name(dt: datetime) -> str:
    """Indonesian day name."""
    names = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
    return names[dt.weekday()]


# ── Registry ──────────────────────────────────────────────

HANDLER_MAP: dict[str, callable] = {
    "send_message": handle_send_message,
    "send_agenda": handle_send_agenda,
    "reminder_alert": handle_reminder_alert,
}


def get_handler(job_type: str) -> callable | None:
    return HANDLER_MAP.get(job_type)
