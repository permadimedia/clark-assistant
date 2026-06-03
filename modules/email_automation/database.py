"""
Email Automation — self-contained SQLite database.

Stores seen messages, new/read state, classification, and scan audit logs.
Uses a separate database file (data/email.db) to keep the plugin decoupled
from core Clark storage.
"""

import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

import aiosqlite

logger = logging.getLogger(__name__)

_TABLE_MESSAGES = """CREATE TABLE IF NOT EXISTS email_messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id      TEXT    NOT NULL,
    provider        TEXT    NOT NULL DEFAULT 'gmail',
    thread_id       TEXT    DEFAULT '',
    from_email      TEXT    NOT NULL,
    from_name       TEXT    DEFAULT '',
    subject         TEXT    NOT NULL,
    snippet         TEXT    DEFAULT '',
    received_at     TEXT,
    is_read         INTEGER DEFAULT 0,
    label_key       TEXT    DEFAULT '',
    first_seen_at   TEXT    NOT NULL,
    last_seen_at    TEXT    NOT NULL,
    is_new          INTEGER DEFAULT 1,
    notified        INTEGER DEFAULT 0,
    created_at      TEXT    DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
)"""

_TABLE_SCAN_LOG = """CREATE TABLE IF NOT EXISTS email_scan_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    scanned_at      TEXT    NOT NULL,
    total_fetched   INTEGER DEFAULT 0,
    total_new       INTEGER DEFAULT 0,
    total_seen      INTEGER DEFAULT 0,
    total_priority  INTEGER DEFAULT 0,
    total_archived  INTEGER DEFAULT 0,
    unclassified    INTEGER DEFAULT 0,
    classified      TEXT    DEFAULT '{}',
    error           TEXT    DEFAULT '',
    duration_ms     INTEGER DEFAULT 0
)"""

_INDEXES = [
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_email_msg_id ON email_messages(provider, message_id)",
    "CREATE INDEX IF NOT EXISTS idx_email_received ON email_messages(received_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_email_new ON email_messages(is_new, label_key)",
    "CREATE INDEX IF NOT EXISTS idx_email_search ON email_messages(from_email, subject)",
    "CREATE INDEX IF NOT EXISTS idx_scan_time ON email_scan_log(scanned_at DESC)",
]


class EmailDatabase:
    """Thin wrapper around aiosqlite for email module data.

    Opens its own connection to a dedicated SQLite file at *db_path*.
    Safe to instantiate once and reuse across the module lifecycle.
    """

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(Path(db_path).expanduser().resolve())
        self._conn: aiosqlite.Connection | None = None

    # ── Connection ──────────────────────────────────────────

    async def connect(self) -> None:
        """Open (or return) aiosqlite connection, creating tables if needed."""
        if self._conn is not None:
            return
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._conn = await aiosqlite.connect(self._db_path)
        self._conn.row_factory = aiosqlite.Row
        try:
            await self._conn.execute("PRAGMA journal_mode=WAL")
        except Exception:
            pass  # WAL mode may fail on some FS (e.g. network mounts)
        await self._conn.execute("PRAGMA synchronous=NORMAL")
        await self._ensure_schema()
        logger.info("EmailDatabase ready at %s", self._db_path)

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def _ensure_schema(self) -> None:
        """Create tables and indexes if they don't exist."""
        # Each statement separately — avoids OOM from massive executescript
        stmts = [_TABLE_MESSAGES, _TABLE_SCAN_LOG] + _INDEXES
        for stmt in stmts:
            try:
                await self._conn.execute(stmt)
            except Exception as exc:
                logger.warning("Schema statement skipped: %s", exc)
        await self._conn.commit()

    # ── CRUD: Messages ─────────────────────────────────────

    async def upsert_message(
        self,
        *,
        message_id: str,
        provider: str,
        thread_id: str,
        from_email: str,
        from_name: str,
        subject: str,
        snippet: str,
        received_at: str,
        is_read: bool,
        label_key: str | None,
    ) -> tuple[str, bool]:
        """Insert a new email or update an existing one.

        Returns:
            (label_key_or_default, was_new) — was_new is True for first-time inserts.
        """
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        label = label_key or ""

        cursor = await self._conn.execute(
            "SELECT id, label_key FROM email_messages WHERE provider=? AND message_id=?",
            (provider, message_id),
        )
        existing = await cursor.fetchone()

        if existing:
            # Already seen → update, mark as no longer new
            await self._conn.execute(
                """UPDATE email_messages
                   SET last_seen_at=?, is_read=?, is_new=0, snippet=?, subject=?
                   WHERE id=?""",
                (now, 1 if is_read else 0, snippet, subject, existing["id"]),
            )
            # Keep original classification, not the updated one
            return existing["label_key"] or label, False

        # New email → insert
        await self._conn.execute(
            """INSERT INTO email_messages
               (message_id, provider, thread_id, from_email, from_name,
                subject, snippet, received_at, is_read, label_key,
                first_seen_at, last_seen_at, is_new, notified)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0)""",
            (
                message_id,
                provider,
                thread_id,
                from_email,
                from_name,
                subject,
                snippet,
                received_at,
                1 if is_read else 0,
                label,
                now,
                now,
            ),
        )
        return label, True

    async def mark_notified(self, message_id: str, provider: str = "gmail") -> None:
        """Mark a message as notified (notification sent)."""
        await self._conn.execute(
            "UPDATE email_messages SET notified=1 WHERE provider=? AND message_id=?",
            (provider, message_id),
        )
        await self._conn.commit()

    async def batch_notified(self, message_ids: list[str], provider: str = "gmail") -> None:
        """Mark multiple messages as notified."""
        if not message_ids:
            return
        placeholders = ",".join("?" for _ in message_ids)
        await self._conn.execute(
            f"UPDATE email_messages SET notified=1 WHERE provider=? AND message_id IN ({placeholders})",
            [provider, *message_ids],
        )
        await self._conn.commit()

    # ── Queries ─────────────────────────────────────────────

    async def get_new_unnotified(self, provider: str = "gmail") -> list[dict]:
        """Fetch messages that are new (first seen) and not yet notified.

        Ordered by priority labels first, then most recent.
        """
        cursor = await self._conn.execute(
            """SELECT * FROM email_messages
               WHERE provider=? AND is_new=1 AND notified=0
               ORDER BY
                   CASE label_key
                       WHEN 'priority_security'   THEN 0
                       WHEN 'priority_billing'    THEN 1
                       WHEN 'priority_user_account' THEN 2
                       WHEN 'followup'            THEN 3
                       WHEN 'archive_notifications' THEN 4
                       WHEN 'archive_promo'       THEN 5
                       WHEN 'archive_social'      THEN 6
                       WHEN 'archive_newsletter'  THEN 7
                       ELSE 8
                   END,
                   received_at DESC
               LIMIT 100""",
            (provider,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_older_unread(self, provider: str = "gmail", limit: int = 20) -> list[dict]:
        """Fetch previously-seen but unread messages (notified+new+unread mix).

        Prioritised by label importance then recency.
        """
        cursor = await self._conn.execute(
            """SELECT * FROM email_messages
               WHERE provider=? AND is_read=0 AND is_new=0
               ORDER BY
                   CASE label_key
                       WHEN 'priority_security'   THEN 0
                       WHEN 'priority_billing'    THEN 1
                       WHEN 'priority_user_account' THEN 2
                       WHEN 'followup'            THEN 3
                       ELSE 4
                   END,
                   received_at DESC
               LIMIT ?""",
            (provider, limit),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def search_messages(
        self,
        query: str,
        provider: str = "gmail",
        limit: int = 30,
    ) -> list[dict]:
        """Search tracked messages by sender or subject (local, instant)."""
        like = f"%{query}%"
        cursor = await self._conn.execute(
            """SELECT * FROM email_messages
               WHERE provider=?
                 AND (from_email LIKE ? OR subject LIKE ?)
               ORDER BY
                   is_new DESC,
                   CASE label_key
                       WHEN 'priority_security'   THEN 0
                       WHEN 'priority_billing'    THEN 1
                       ELSE 2
                   END,
                   received_at DESC
               LIMIT ?""",
            (provider, like, like, limit),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_daily_stats(self, provider: str = "gmail") -> dict:
        """Get summary stats for notifications footer."""
        cursor = await self._conn.execute(
            "SELECT COUNT(*) FROM email_messages WHERE provider=?",
            (provider,),
        )
        total = (await cursor.fetchone())[0]

        cursor = await self._conn.execute(
            "SELECT COUNT(*) FROM email_messages WHERE provider=? AND is_new=1 AND notified=0",
            (provider,),
        )
        new_unnotified = (await cursor.fetchone())[0]

        cursor = await self._conn.execute(
            "SELECT COUNT(*) FROM email_messages WHERE provider=? AND is_read=0 AND is_new=0",
            (provider,),
        )
        older_unread = (await cursor.fetchone())[0]

        return {
            "total_tracked": total,
            "new_unnotified": new_unnotified,
            "older_unread": older_unread,
            "read": total - new_unnotified - older_unread,
        }

    # ── Scan Logging ────────────────────────────────────────

    async def log_scan(
        self,
        *,
        total_fetched: int,
        total_new: int,
        total_seen: int,
        total_priority: int,
        total_archived: int,
        unclassified: int,
        classified: dict[str, int],
        duration_ms: int,
        error: str = "",
    ) -> None:
        """Record a scan event for audit / debugging."""
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        await self._conn.execute(
            """INSERT INTO email_scan_log
               (scanned_at, total_fetched, total_new, total_seen,
                total_priority, total_archived, unclassified, classified,
                error, duration_ms)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                now,
                total_fetched,
                total_new,
                total_seen,
                total_priority,
                total_archived,
                unclassified,
                json.dumps(classified),
                error,
                duration_ms,
            ),
        )
        await self._conn.commit()

    async def get_recent_scans(self, limit: int = 10) -> list[dict]:
        """Fetch most recent scan log entries."""
        cursor = await self._conn.execute(
            "SELECT * FROM email_scan_log ORDER BY scanned_at DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # ── Maintenance ─────────────────────────────────────────

    async def vacuum(self) -> None:
        """Recover disk space after deletes/updates."""
        await self._conn.execute("PRAGMA incremental_vacuum")
        await self._conn.commit()
