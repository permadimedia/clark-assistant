"""Email Engine — core orchestration: connect → scan → classify → label → notify.

Now with EmailDatabase integration:
- Deduplicates against previous scans via message_id
- Tracks is_new / notified / first_seen / last_seen
- Only surfaces new+unread items in notifications
- Logs every scan to email_scan_log for audit
"""

import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

from modules.email_automation.providers.base import EmailMessage, EmailProvider
from modules.email_automation.labels import LABELS
from modules.email_automation.classifier import classify, classify_many
from modules.email_automation.formatter import format_daily_summary, format_new_notifications
from modules.email_automation.database import EmailDatabase

logger = logging.getLogger(__name__)

WIB = timezone(timedelta(hours=7))


class EmailEngine:
    """Orchestrates email scanning, classification, cleanup, and notification.

    Provider-agnostic — works with any EmailProvider implementation.
    Database-backed for dedup, new/seen tracking, and scan audit.
    """

    def __init__(
        self,
        provider_type: str = "gmail",
        credentials_path: str = "~/.config/email/credentials.json",
        token_path: str = "~/.config/email/token.json",
        scan_limit: int = 50,
        read_only: bool = True,
        archive_read_after_days: int = 90,
        trash_draft_after_days: int = 30,
        db: Optional[EmailDatabase] = None,
    ):
        self.provider_type = provider_type
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.scan_limit = scan_limit
        self.read_only = read_only
        self.archive_read_after_days = archive_read_after_days
        self.trash_draft_after_days = trash_draft_after_days
        self.db = db or EmailDatabase("~/.clark/email.db")

        self.provider: EmailProvider | None = None
        self.last_scan_at: str | None = None
        self.last_summary: dict | None = None

    # ── Lifecycle ───────────────────────────────────────────

    async def connect(self) -> bool:
        """Initialize provider and database, connect provider."""
        await self.db.connect()

        if self.provider_type == "gmail":
            from modules.email_automation.providers.gmail import GmailProvider
            self.provider = GmailProvider(
                credentials_path=self.credentials_path,
                token_path=self.token_path,
                read_only=self.read_only,
            )
        else:
            logger.error("Unsupported provider type: %s", self.provider_type)
            return False

        creds = self._load_credentials()
        ok = await self.provider.connect(creds)
        if ok:
            logger.info("Engine connected (%s)", self.provider_type)
        else:
            logger.error("Engine failed to connect (%s)", self.provider_type)
        return ok

    async def disconnect(self) -> None:
        """Disconnect provider and close database."""
        if self.provider:
            await self.provider.disconnect()
            self.provider = None
        await self.db.close()
        logger.info("Engine disconnected")

    # ── Scan ────────────────────────────────────────────────

    async def scan(self) -> dict:
        """Run a full scan cycle: fetch → classify → upsert DB → log.

        Returns dict with scan results, new/seen counts, and formatted summary.
        Only new items (first-seen and not-yet-notified) are included for notification.
        """
        start_ms = int(time.time() * 1000)

        if not self.provider:
            ok = await self.connect()
            if not ok:
                return {"total": 0, "error": "Provider not connected"}

        # 1. Fetch inbox metadata
        messages = await self.provider.list_inbox(limit=self.scan_limit)
        if not messages:
            await self.db.log_scan(
                total_fetched=0, total_new=0, total_seen=0,
                total_priority=0, total_archived=0, unclassified=0,
                classified={}, duration_ms=int(time.time() * 1000) - start_ms,
                error="No messages found",
            )
            return self._empty_result("No messages found")

        # 2. Classify all messages
        classified_groups = classify_many(messages)
        label_map: dict[str, str] = {}
        for label_key, msg_list in classified_groups.items():
            for msg in msg_list:
                label_map[msg.id] = label_key

        # 3. Upsert each message into DB — classify first, then store
        new_msg_ids: list[str] = []
        seen_msg_ids: list[str] = []
        new_classified_counts: dict[str, int] = {}

        for msg in messages:
            msg_label = label_map.get(msg.id, classify(msg))
            label_key, was_new = await self.db.upsert_message(
                message_id=msg.id,
                provider=self.provider_type,
                thread_id=msg.thread_id,
                from_email=msg.from_email,
                from_name=msg.from_name or "",
                subject=msg.subject,
                snippet=msg.snippet[:150] if msg.snippet else "",
                received_at=msg.received_at,
                is_read=msg.is_read,
                label_key=msg_label,
            )
            if was_new:
                new_msg_ids.append(msg.id)
                new_classified_counts[msg_label or "_unclassified"] = (
                    new_classified_counts.get(msg_label or "_unclassified", 0) + 1
                )
            else:
                seen_msg_ids.append(msg.id)

        # 4. Apply labels + archive (write mode only)
        labels_applied = 0
        archived_count = 0
        if not self.read_only and self.provider is not None:
            for label_key, msg_list in classified_groups.items():
                label_def = LABELS.get(label_key)
                if not label_def:
                    continue
                for msg in msg_list:
                    if await self.provider.apply_labels(msg.id, [label_def.name]):
                        labels_applied += 1

            for lk in ["archive_promo", "archive_newsletter", "archive_social", "archive_notifications"]:
                for msg in classified_groups.get(lk, []):
                    if await self.provider.archive(msg.id):
                        archived_count += 1

        # 5. Get storage info
        storage = await self.provider.get_storage_info()

        # 6. Compute counts
        priority_count = sum(
            len(classified_groups.get(k, []))
            for k in ["priority_security", "priority_billing", "priority_user_account", "followup"]
            if k in classified_groups
        )

        total_new = len(new_msg_ids)
        total_seen = len(seen_msg_ids)

        duration_ms = int(time.time() * 1000) - start_ms

        # 7. Log scan to DB
        await self.db.log_scan(
            total_fetched=len(messages),
            total_new=total_new,
            total_seen=total_seen,
            total_priority=priority_count,
            total_archived=archived_count,
            unclassified=new_classified_counts.get("_unclassified", 0),
            classified={k: len(v) for k, v in classified_groups.items()},
            duration_ms=duration_ms,
            error="",
        )

        self.last_scan_at = datetime.now(WIB).strftime("%Y-%m-%d %H:%M:%S WIB")
        self.last_summary = {
            "total": len(messages),
            "new": total_new,
            "seen": total_seen,
            "priority_count": priority_count,
            "archived_count": archived_count,
            "labels_applied": labels_applied,
            "storage": storage,
        }

        # 8. Format notification — only new + unread items
        summary_text = await self._format_notification()

        result = {
            "total": len(messages),
            "new": total_new,
            "seen": total_seen,
            "priority_count": priority_count,
            "labels_applied": labels_applied,
            "classified": {k: len(v) for k, v in classified_groups.items()},
            "summary": summary_text,
            "last_scan_at": self.last_scan_at,
        }

        logger.info(
            "Scan: %d fetched, %d new, %d seen, %d priority (%dms)",
            len(messages), total_new, total_seen, priority_count, duration_ms,
        )

        return result

    # ── Notifications ───────────────────────────────────────

    async def _format_notification(self) -> str:
        """Build notification text from DB — new items + older unread + summary."""
        new_items = await self.db.get_new_unnotified(provider=self.provider_type)
        older_unread = await self.db.get_older_unread(provider=self.provider_type)
        stats = await self.db.get_daily_stats(provider=self.provider_type)

        return format_new_notifications(
            new_items=new_items,
            older_unread=older_unread,
            stats=stats,
            scan_time=self.last_scan_at or "",
        )

    async def mark_notified(self, message_ids: list[str]) -> None:
        """Mark messages as notified after sending."""
        await self.db.batch_notified(message_ids, provider=self.provider_type)

    # ── Targeted Search ────────────────────────────────────

    async def search(self, query: str) -> dict:
        """Search tracked email messages locally (instant, no API call).

        Falls back to a fresh scan if no local results found.
        """
        results = await self.db.search_messages(query, provider=self.provider_type)
        if results:
            return {
                "source": "local_db",
                "count": len(results),
                "messages": results,
            }

        # Fallback: scan and search again
        await self.scan()
        results = await self.db.search_messages(query, provider=self.provider_type)
        return {
            "source": "fresh_scan" if results else "none",
            "count": len(results),
            "messages": results,
        }

    # ── Cleanup ─────────────────────────────────────────────

    async def cleanup(self, archive_days: int = 90, draft_days: int = 30) -> dict:
        """Execute cleanup: archive read emails, delete old drafts.

        Only available in non-read-only mode.
        """
        if self.read_only:
            return {"error": "Read-only mode", "drafts_deleted": 0, "archived_count": 0}

        if not self.provider:
            ok = await self.connect()
            if not ok:
                return {"error": "Provider not connected", "drafts_deleted": 0, "archived_count": 0}

        drafts = await self.provider.list_drafts(limit=20)
        deleted = 0
        archived = 0

        for draft in drafts:
            if not draft.subject or draft.subject == "(no subject)":
                ok = await self.provider.trash(draft.id)
                if ok:
                    deleted += 1

        return {"drafts_deleted": deleted, "archived_count": archived}

    # ─── Status ─────────────────────────────────────────────

    async def get_status(self) -> dict:
        """Return engine status with DB stats."""
        stats = {"total_tracked": 0, "new_unnotified": 0, "older_unread": 0, "read": 0}
        recent_scans = []
        try:
            stats = await self.db.get_daily_stats(provider=self.provider_type)
            recent_scans = await self.db.get_recent_scans(limit=5)
        except Exception:
            pass

        return {
            "provider": self.provider_type,
            "status": "connected" if self.provider else "disconnected",
            "read_only": self.read_only,
            "last_scan_at": self.last_scan_at,
            "last_scan_summary": self.last_summary,
            "stats": stats,
            "recent_scans": [
                {
                    "scanned_at": r["scanned_at"],
                    "fetched": r["total_fetched"],
                    "new": r["total_new"],
                    "seen": r["total_seen"],
                    "priority": r["total_priority"],
                    "duration_ms": r["duration_ms"],
                    "error": r["error"],
                }
                for r in recent_scans
            ],
        }

    # ── Internal ────────────────────────────────────────────

    def _load_credentials(self) -> dict | None:
        import json
        from pathlib import Path

        path = Path(self.credentials_path).expanduser()
        if path.exists():
            try:
                return json.loads(path.read_text())
            except Exception as e:
                logger.warning("Failed to load credentials from %s: %s", path, e)
        return None

    def _empty_result(self, reason: str) -> dict:
        return {
            "total": 0,
            "new": 0,
            "seen": 0,
            "priority_count": 0,
            "labels_applied": 0,
            "classified": {},
            "summary": f"📬 Scan — no results: {reason}",
            "last_scan_at": self.last_scan_at or "",
        }
