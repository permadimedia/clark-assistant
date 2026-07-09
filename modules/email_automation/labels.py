"""Label definitions and strategy for email automation.

Convention:
  ! prefix = priority label (visible in inbox, user should act)
  _ prefix = archive label (skip inbox, informational)
"""

from dataclasses import dataclass, field


@dataclass
class LabelDef:
    """A single label definition."""
    name: str           # Gmail label name
    emoji: str          # Display emoji
    category: str       # Category group
    priority: bool      # Show in priority notifications
    auto_archive: bool  # Auto-archive (skip inbox)


# ── Labels ─────────────────────────────────────────────────

LABELS = {
    "priority_security": LabelDef(
        name="!Priority/Security",
        emoji="🔒",
        category="security",
        priority=True,
        auto_archive=False,
    ),
    "priority_billing": LabelDef(
        name="!Priority/Billing",
        emoji="💳",
        category="billing",
        priority=True,
        auto_archive=False,
    ),
    "priority_user_account": LabelDef(
        name="!Priority/User-Account",
        emoji="👤",
        category="user_account",
        priority=True,
        auto_archive=False,
    ),
    "followup": LabelDef(
        name="!Followup",
        emoji="📋",
        category="followup",
        priority=True,
        auto_archive=False,
    ),
    "archive_promo": LabelDef(
        name="_Archive/Promo",
        emoji="📢",
        category="promo",
        priority=False,
        auto_archive=True,
    ),
    "archive_newsletter": LabelDef(
        name="_Archive/Newsletter",
        emoji="🗞️",
        category="newsletter",
        priority=False,
        auto_archive=True,
    ),
    "archive_social": LabelDef(
        name="_Archive/Social",
        emoji="👥",
        category="social",
        priority=False,
        auto_archive=True,
    ),
    "archive_notifications": LabelDef(
        name="_Archive/Notifications",
        emoji="🔔",
        category="notifications",
        priority=False,
        auto_archive=True,
    ),
    "trash_old_drafts": LabelDef(
        name="_Trash/Old-Drafts",
        emoji="🗑️",
        category="trash_drafts",
        priority=False,
        auto_archive=True,
    ),
    "trash_read_archived": LabelDef(
        name="_Trash/Read-Archived",
        emoji="🗑️",
        category="trash_read",
        priority=False,
        auto_archive=True,
    ),
}


def get_label(key: str) -> LabelDef | None:
    """Get label definition by key."""
    return LABELS.get(key)


def priority_labels() -> list[LabelDef]:
    """Get all priority labels (for notification)."""
    return [l for l in LABELS.values() if l.priority]


def archive_labels() -> list[LabelDef]:
    """Get all archive labels."""
    return [l for l in LABELS.values() if l.auto_archive]
