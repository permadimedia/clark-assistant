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


# ── New notification format (DB-backed) ────────────────────


def format_new_notifications(
    new_items: list[dict],
    older_unread: list[dict],
    stats: dict,
    scan_time: str = "",
    user_name: str = "User",
) -> str:
    """Format scan results with NEW / OLDER UNREAD / summary sections.

    Args:
        new_items: DB rows with is_new=1, notified=0 (from get_new_unnotified).
        older_unread: DB rows with is_read=0, is_new=0 (from get_older_unread).
        stats: Daily stats dict (total_tracked, new_unnotified, older_unread, read).
        scan_time: Human-readable scan timestamp.
        user_name: Display name.

    Returns:
        Formatted Telegram message string.
    """
    now = datetime.now(WIB)
    date_str = now.strftime("%a, %b %d, %Y")

    lines = [
        f"📬 Email Daily — {user_name}, {date_str}",
        "",
    ]

    # ── NEW section ────────────────────────────────────────
    if new_items:
        lines.append(f"🆕 NEW — {len(new_items)} email{'s' if len(new_items) != 1 else ''}")
        lines.append("")
        _append_grouped_rows(lines, new_items, show_new_badge=False)
    else:
        lines.append("🆕 No new emails since last scan")

    lines.append("")

    # ── OLDER UNREAD section ───────────────────────────────
    if older_unread:
        lines.append(f"📌 OLDER UNREAD — {len(older_unread)} email{'s' if len(older_unread) != 1 else ''}")
        lines.append("")
        _append_grouped_rows(lines, older_unread, show_new_badge=False)

    # ── Summary footer ─────────────────────────────────────
    lines.append("━" * 25)
    lines.append(f"📊 {stats.get('new_unnotified', 0)} new · {stats.get('older_unread', 0)} unread · {stats.get('read', 0)} read")
    if scan_time:
        lines.append(f"Last scan: {scan_time}")
    lines.append("")
    lines.append("📌 /scan to refresh · /email search [keyword]")
    lines.append("🦊 <i>clark</i>")

    return "\n".join(lines)


def _append_grouped_rows(lines: list[str], items: list[dict], show_new_badge: bool = False) -> None:
    """Append formatted email rows grouped by label_key."""
    from collections import defaultdict

    groups: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        label = item.get("label_key", "") or "unclassified"
        groups[label].append(item)

    # Order: priority labels first, then the rest
    label_order = [
        "priority_security",
        "priority_billing",
        "priority_user_account",
        "followup",
        "archive_notifications",
        "archive_promo",
        "archive_social",
        "archive_newsletter",
    ]
    sorted_keys = sorted(groups, key=lambda k: label_order.index(k) if k in label_order else 99)

    for i, label_key in enumerate(sorted_keys):
        group_items = groups[label_key]
        label_def = LABELS.get(label_key)
        emoji = label_def.emoji if label_def else "📄"
        group_name = label_def.name.split("/")[-1] if label_def else label_key.replace("_", " ").title()

        # Section header
        lines.append(f"{emoji} {group_name}")

        for item in group_items:
            time_str = _format_time_str(item.get("received_at", ""))
            sender = item.get("from_name", "") or item.get("from_email", "")
            subject = item.get("subject", "(no subject)")
            snippet = item.get("snippet", "")

            lines.append(f"  from: {sender}")
            lines.append(f"  {subject}")
            if time_str:
                lines.append(f"  📅 {time_str}")
            if snippet:
                # Truncate snippet to avoid line-noise
                s = snippet[:100]
                lines.append(f"  💬 {s}")
            lines.append("")

        if i < len(sorted_keys) - 1:
            lines.append("")


def _format_time_str(received_at: str | None) -> str:
    """Format an ISO-8601 datetime string for display."""
    if not received_at:
        return ""
    try:
        dt = datetime.fromisoformat(received_at)
        local = dt.astimezone(WIB)
        now = datetime.now(WIB)
        if local.date() == now.date():
            return f"Today {local.strftime('%H:%M')}"
        delta = now - local
        if delta.days == 1 and delta.total_seconds() < 48 * 3600:
            return f"Yesterday {local.strftime('%H:%M')}"
        elif delta.days < 7:
            return local.strftime("%a %H:%M")
        else:
            return local.strftime("%b %d, %H:%M")
    except Exception:
        return received_at
