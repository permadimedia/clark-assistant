"""Notes CRUD API endpoints."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from core.config import settings
from core.database import get_db

router = APIRouter(prefix="/api/notes", tags=["notes"])

WIB = timezone(timedelta(hours=7))
USER_CHAT_ID = settings.telegram_chat_id


# ── Models ──────────────────────────────────────────────────

class NoteCreate(BaseModel):
    text: str
    chat_id: int = 0


class NoteUpdate(BaseModel):
    text: str


class NoteResponse(BaseModel):
    id: int
    text: str
    chat_id: int
    created_at: str | None = None


# ── Endpoints ──────────────────────────────────────────────

@router.post("", response_model=NoteResponse)
async def create_note(body: NoteCreate):
    """Save a new note."""
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="Cannot save empty note")

    chat_id = body.chat_id if body.chat_id else USER_CHAT_ID
    db = await get_db()
    cursor = await db.execute(
        "INSERT INTO notes (chat_id, text) VALUES (?, ?)",
        (chat_id, body.text.strip()),
    )
    note_id = cursor.lastrowid
    await db.commit()
    now_str = datetime.now(timezone.utc).isoformat()
    return NoteResponse(id=note_id, text=body.text.strip(), chat_id=chat_id, created_at=now_str)


@router.get("", response_model=list[NoteResponse])
async def list_notes(limit: int = Query(default=50, ge=1, le=200)):
    """List all notes."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT id, text, chat_id, created_at FROM notes "
        "WHERE chat_id = ? ORDER BY created_at DESC LIMIT ?",
        (USER_CHAT_ID, limit),
    )
    rows = await cursor.fetchall()
    return [NoteResponse(id=r["id"], text=r["text"], chat_id=r["chat_id"], created_at=r["created_at"]) for r in rows]


@router.get("/search", response_model=list[NoteResponse])
async def search_notes(q: str):
    """Search notes by keyword via FTS5."""
    if not q.strip():
        raise HTTPException(status_code=400, detail="Query 'q' is required")
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT rowid as id, text FROM notes_fts "
            "WHERE notes_fts MATCH ? AND chat_id = ? ORDER BY rank LIMIT 10",
            (q.strip(), USER_CHAT_ID),
        )
        rows = await cursor.fetchall()
    except Exception:
        rows = []
    return [NoteResponse(id=r["id"], text=r["text"], chat_id=USER_CHAT_ID) for r in rows]


@router.get("/{note_id}", response_model=NoteResponse)
async def get_note(note_id: int):
    """Get a single note by ID."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT id, text, chat_id, created_at FROM notes WHERE id = ? AND chat_id = ?",
        (note_id, USER_CHAT_ID),
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Note not found")
    return NoteResponse(id=row["id"], text=row["text"], chat_id=row["chat_id"], created_at=row["created_at"])


@router.put("/{note_id}", response_model=NoteResponse)
async def update_note(note_id: int, body: NoteUpdate):
    """Update a note's content."""
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="Cannot save empty note")
    db = await get_db()
    cursor = await db.execute(
        "UPDATE notes SET text = ? WHERE id = ? AND chat_id = ?",
        (body.text.strip(), note_id, USER_CHAT_ID),
    )
    await db.commit()
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Note not found")
    cursor = await db.execute("SELECT id, text, chat_id, created_at FROM notes WHERE id = ?", (note_id,))
    row = await cursor.fetchone()
    return NoteResponse(id=row["id"], text=row["text"], chat_id=row["chat_id"], created_at=row["created_at"])


@router.delete("/{note_id}")
async def delete_note(note_id: int):
    """Delete a note."""
    db = await get_db()
    cursor = await db.execute(
        "DELETE FROM notes WHERE id = ? AND chat_id = ?",
        (note_id, USER_CHAT_ID),
    )
    await db.commit()
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Note not found")
    return {"status": "deleted", "id": note_id}
