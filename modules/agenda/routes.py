"""Agenda query API endpoints."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from core.config import settings
from core.database import get_db

router = APIRouter(prefix="/api/agenda", tags=["agenda"])

WIB = timezone(timedelta(hours=7))
USER_CHAT_ID = settings.telegram_chat_id


# ── Models ──────────────────────────────────────────────────

class AgendaItem(BaseModel):
    id: int
    text: str
    time: str
    done: bool


class AgendaResponse(BaseModel):
    date: str
    items: list[AgendaItem]
    total: int
    done_count: int


# ── Helpers ────────────────────────────────────────────────

def _agenda_date(dt: datetime) -> str:
    return dt.astimezone(WIB).strftime("%Y-%m-%d")


async def _query_agenda(chat_id: int, date_str: str) -> list[dict]:
    db = await get_db()
    cursor = await db.execute(
        "SELECT id, text, remind_at, fired FROM reminders "
        "WHERE chat_id = ? AND DATE(remind_at) = ? ORDER BY remind_at ASC",
        (chat_id, date_str),
    )
    rows = await cursor.fetchall()
    result = []
    for r in rows:
        dt = datetime.fromisoformat(r["remind_at"])
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        local = dt.astimezone(WIB)
        result.append({"id": r["id"], "text": r["text"], "time": local.strftime("%H:%M"), "done": bool(r["fired"])})
    return result


# ── Endpoints ──────────────────────────────────────────────

@router.get("", response_model=AgendaResponse)
async def get_agenda(
    date: str | None = Query(default=None, description="YYYY-MM-DD"),
    range: str | None = Query(default=None, description="today | tomorrow | week"),
):
    """Get agenda items."""
    now = datetime.now(WIB)

    if range == "tomorrow":
        target = now + timedelta(days=1)
        date_str = _agenda_date(target)
    elif range == "week":
        items = []
        for i in range(7):
            target = now + timedelta(days=i)
            items.extend(await _query_agenda(USER_CHAT_ID, _agenda_date(target)))
        done_count = sum(1 for it in items if it["done"])
        return AgendaResponse(date="week", items=[AgendaItem(**it) for it in items], total=len(items), done_count=done_count)
    elif date:
        date_str = date
    else:
        date_str = _agenda_date(now)

    items = await _query_agenda(USER_CHAT_ID, date_str)
    done_count = sum(1 for it in items if it["done"])
    return AgendaResponse(date=date_str, items=[AgendaItem(**it) for it in items], total=len(items), done_count=done_count)


@router.post("/{reminder_id}/done")
async def mark_done(reminder_id: int):
    """Mark agenda item done."""
    db = await get_db()
    cursor = await db.execute(
        "UPDATE reminders SET fired = 1 WHERE id = ? AND chat_id = ? AND fired = 0",
        (reminder_id, USER_CHAT_ID),
    )
    await db.commit()
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Item not found or already done")
    return {"status": "done", "id": reminder_id}


@router.post("/done-all")
async def mark_all_done():
    """Mark all today's items done."""
    today_str = _agenda_date(datetime.now(WIB))
    db = await get_db()
    cursor = await db.execute(
        "UPDATE reminders SET fired = 1 WHERE chat_id = ? AND fired = 0 AND DATE(remind_at) = ?",
        (USER_CHAT_ID, today_str),
    )
    await db.commit()
    return {"status": "done_all", "count": cursor.rowcount, "date": today_str}
