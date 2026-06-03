"""Email Engine — core orchestration: connect → scan → classify → label → notify."""

import logging
from datetime import datetime, timezone, timedelta

from modules.email_automation.providers.base import EmailMessage, EmailProvider
from modules.email_automation.labels import LABELS
from modules.email_automation.classifier import classify_many
from modules.email_automation.formatter import format_daily_summary

logger = logging.getLogger(__name__)

WIB = timezone(timedelta(hours=7))


class EmailEngine:
    """Orchestrates email scanning, classification, and cleanup.

    Provider-agnostic — works with any EmailProvider implementation.
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
    ):
        self.provider_type = provider_type
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.scan_limit = scan_limit
        self.read_only = read_only
        self.archive_read_after_days = archive_read_after_days
        self.trash_draft_after_days = trash_draft_after_days

        self.provider: EmailProvider | None = None
        self.last_scan_at: str | None = None
        self.last_summary: dict | None = None

    # ── Lifecycle ───────────────────────────────────────────

    async def connect(self) -> bool:
        """Initialize and connect the email provider."""
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
        """Disconnect provider."""
        if self.provider:
            await self.provider.disconnect()
            self.provider = None
        logger.info("Engine disconnected")

    # ── Scan ────────────────────────────────────────────────

    async def scan(self) -> dict:
        """Run a full scan cycle: fetch → classify → label → summarize.

        Returns dict with scan results and formatted summary.
        """
        if not self.provider:
            ok = await self.connect()
            if not ok:
                return {"total": 0, "error": "Provider not connected"}

        # 1. Fetch inbox metadata
        messages = await self.provider.list_inbox(limit=self.scan_limit)
        if not messages:
            return self._empty_result("No messages found")

        # 2. Fetch drafts (for cleanup suggestions)
        drafts = await self.provider.list_drafts(limit=20)

        # 3. Classify
        classified = classify_many(messages)

        # 4. Apply labels (only if write mode)
        labels_applied = 0
        if not self.read_only and self.provider is not None:
            for label_key, msg_list in classified.items():
                label_def = LABELS.get(label_key)
                if not label_def:
                    continue
                for msg in msg_list:
                    ok = await self.provider.apply_labels(msg.id, [label_def.name])
                    if ok:
                        labels_applied += 1

            # Auto-archive
            archived_count = 0
            for label_key in ["archive_promo", "archive_newsletter", "archive_social", "archive_notifications"]:
                msg_list = classified.get(label_key, [])
                for msg in msg_list:
                    ok = await self.provider.archive(msg.id)
                    if ok:
                        archived_count += 1
        else:
            archived_count = 0

        # 5. Get storage info
        storage = await self.provider.get_storage_info()

        # 6. Generate summary
        priority_count = sum(
            len(classified.get(k, []))
            for k in ["priority_security", "priority_billing", "priority_user_account", "followup"]
            if k in classified
        )

        self.last_scan_at = datetime.now(WIB).strftime("%Y-%m-%d %H:%M:%S WIB")
        self.last_summary = {
            "total": len(messages) + len(drafts),
            "priority_count": priority_count,
            "archived_count": archived_count,
            "labels_applied": labels_applied,
            "draft_count": len(drafts),
            "storage": storage,
        }

        # 7. Format notification
        summary_text = format_daily_summary(
            messages=messages + drafts,
            classified=classified,
            stats=storage,
        )

        result = {
            "total": len(messages) + len(drafts),
            "messages": len(messages),
            "drafts": len(drafts),
            "priority_count": priority_count,
            "archived_count": archived_count,
            "labels_applied": labels_applied,
            "classified": {k: len(v) for k, v in classified.items()},
            "summary": summary_text,
        }

        logger.info(
            "Scan complete: %d messages, %d priority, %d archived, %d labels",
            result["total"], priority_count, archived_count, labels_applied,
        )

        return result

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

        # Future: implement archive old read emails
        # For now, just delete empty drafts
        drafts = await self.provider.list_drafts(limit=20)
        deleted = 0
        archived = 0

        for draft in drafts:
            # Delete empty drafts (no subject, no snippet)
            if not draft.subject or draft.subject == "(no subject)":
                ok = await self.provider.trash(draft.id)
                if ok:
                    deleted += 1

        return {
            "drafts_deleted": deleted,
            "archived_count": archived,
        }

    # ── Internal ────────────────────────────────────────────

    def _load_credentials(self) -> dict | None:
        """Load credentials from credentials_path."""
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
            "messages": 0,
            "drafts": 0,
            "priority_count": 0,
            "archived_count": 0,
            "labels_applied": 0,
            "classified": {},
            "summary": f"📬 Scan — no results: {reason}",
        }
