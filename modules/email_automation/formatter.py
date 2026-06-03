"""Telegram notification formatter — turns scan results into smart notifications."""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from modules.email_automation.providers.base import EmailMessage
from modules.email_automation.labels import LABELS, LabelDef

logger = logging.getLogger(__name__)

WIB = timezone(timedelta(hours=7))


def format_daily_summary(
    messages: list[EmailMessage],
    classified: dict[str, list[EmailMessage]],
    stats: dict | None = None,
    user_name: str = "User",
    date: Optional[datetime] = None,
) -> str:
    """Format scan results into a Telegram smart notification.

    Args:
        messages: Full list of fetched messages.
        classified: dict mapping label_key → list[EmailMessage].
        stats: Optional dict with storage info, counts, etc.
        user_name: Display name for greeting.
        date: Scan date (defaults to now WIB).

    Returns:
        Formatted Telegram message string (HTML).
    """
    if date is None:
        date = datetime.now(WIB)

    # Header
    day_name = date.strftime("%a")
    date_str = date.strftime("%b %d %Y")
    lines = [
        f"📬 <b>Email Daily</b> — {user_name}, {day_name} {date_str}",
        "━" * 25,
    ]

    # ── Priority section ────────────────────────────────────
    priority_keys = [k for k in classified if k in _priority_label_keys()]
    if priority_keys:
        lines.append("")
        lines.append("! <b>PRIORITY — Action Required</b>")
        lines.append("")

        for label_key in ["priority_security", "priority_billing", "priority_user_account", "followup"]:
            msgs = classified.get(label_key, [])
            if not msgs:
                continue
            label_def = LABELS.get(label_key)
            if not label_def:
                continue

            lines.append(f"  {label_def.emoji} {label_def.name.split('/')[-1]}")
            lines.append("  " + "─" * 29)

            for msg in msgs[:5]:  # Max 5 per category
                time_str = _format_time(msg.received_at)
                snippet = f" → \"{msg.snippet}\"" if msg.snippet else ""

                lines.append(f"  from: {msg.from_email}")
                lines.append(f"  subject: {msg.subject}")
                if snippet:
                    lines.append(f"  {snippet}")
                lines.append(f"  🏷️ → {label_def.name}")
                if msg.received_at:
                    lines.append(f"  🕐 {time_str}")
                lines.append("")

            if len(msgs) > 5:
                lines.append(f"  … and {len(msgs) - 5} more")
                lines.append("")

    # ── Summary section ─────────────────────────────────────
    lines.append("━" * 25)
    lines.append("📊 <b>Summary</b>")
    lines.append("")

    total = len(messages)
    unread = sum(1 for m in messages if not m.is_read)
    read = total - unread
    lines.append(f"  • {total} new emails ({unread} unread, {read} read)")

    # Breakdown by archive status
    archive_keys = [k for k in classified if k in _archive_label_keys()]
    archive_total = sum(len(classified[k]) for k in archive_keys)
    if archive_total > 0:
        for label_key in ["archive_promo", "archive_newsletter", "archive_social", "archive_notifications"]:
            count = len(classified.get(label_key, []))
            if count > 0:
                label_def = LABELS.get(label_key)
                emoji = label_def.emoji if label_def else "📁"
                short = label_def.name.split("/")[-1] if label_def else label_key
                lines.append(f"  {emoji} {count} {short}")

    # Followup count
    followup_count = len(classified.get("followup", []))
    if followup_count > 0:
        lines.append(f"  📋 {followup_count} follow-up needed")

    # Storage info
    if stats and stats.get("used_bytes"):
        used_mb = stats["used_bytes"] / (1024**2)
        total_mb = stats.get("total_bytes", 15 * 1024**3) / (1024**2)
        lines.append(f"  💾 Storage: {used_mb:.0f} MB / {total_mb:.0f} MB")

    # Draft cleanup suggestion
    draft_count = len([m for m in messages if m.is_draft])
    if draft_count > 0:
        lines.append(f"  🗑️ {draft_count} drafts — reply /cleanup to remove")

    # Footer
    lines.append("")
    lines.append("📌 Reply /scan to check now · /cleanup to archive & trash")
    lines.append("🦊 <i>clark</i>")

    return "\n".join(lines)


def format_scan_progress(current: int, total: int) -> str:
    """Simple progress message during scan (not used in final output)."""
    return f"Scanning… {current}/{total} messages"


# ── Internal ────────────────────────────────────────────────

def _format_time(dt: Optional[datetime]) -> str:
    """Format datetime for display."""
    if dt is None:
        return ""
    try:
        local = dt.astimezone(WIB)
        now = datetime.now(WIB)
        if local.date() == now.date():
            return local.strftime("%H:%M")
        elif (now - local).days < 7:
            return local.strftime("%a %H:%M")
        else:
            return local.strftime("%b %d")
    except Exception:
        return ""


def _priority_label_keys() -> set[str]:
    return {"priority_security", "priority_billing", "priority_user_account", "followup"}


def _archive_label_keys() -> set[str]:
    return {"archive_promo", "archive_newsletter", "archive_social", "archive_notifications"}
