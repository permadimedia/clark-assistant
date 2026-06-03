"""Rule-based email classifier — no ML, no external APIs.

Classification uses only metadata (from_email, subject, headers).
No body content is ever accessed.
"""

import re
from typing import Optional

from modules.email_automation.providers.base import EmailMessage
from modules.email_automation.labels import LabelDef, LABELS


# ── Detection rules ────────────────────────────────────────

# Priority: sender domain matches
_PRIORITY_DOMAINS: dict[str, str] = {
    # These are examples — users can customize via config
}

# Social media domains
_SOCIAL_DOMAINS = [
    "facebook.com", "fb.com", "linkedin.com", "twitter.com",
    "x.com", "instagram.com", "tiktok.com", "youtube.com",
    "github.com", "medium.com", "reddit.com", "pinterest.com",
]

# Bulk email headers
_BULK_HEADERS = [
    "list-id", "list-unsubscribe", "x-mailer",
]

# Subject keywords — grouped by category
_SUBJECT_RULES: list[tuple[str, str, list[str]]] = [
    # (category, label_key, keyword_patterns)
    ("security", "priority_security", [
        r"password", r"login", r"2fa", r"two.?factor", r"security",
        r"suspicious", r"verified", r"authentication", r"sign.?in",
        r"breach", r"blocked", r"unauthorized", r"account.*alert",
        r"secure your account", r"unusual sign",
    ]),
    ("billing", "priority_billing", [
        r"invoice", r"receipt", r"payment", r"bill", r"subscription",
        r"billing", r"transaction", r"statement", r"tagihan",
        r"paid", r"payment confirm", r"your.*receipt",
        r"automatic payment", r"charge",
    ]),
    ("user_account", "priority_user_account", [
        r"welcome", r"registered", r"verification", r"verify",
        r"account", r"sign.?up", r"activation", r"confirm",
        r"onboarding", r"your account.*created",
        r"email.*confirm", r"activate your",
    ]),
    ("promo", "archive_promo", [
        r"promo", r"discount", r"sale", r"offer", r"deal",
        r"coupon", r"save", r"free", r"limited time",
        r"shop now", r"buy now", r"exclusive",
    ]),
    ("notifications", "archive_notifications", [
        r"notification", r"alert", r"update", r"status",
        r"delivery", r"tracking", r"shipped", r"out for delivery",
    ]),
]


def classify(message: EmailMessage) -> Optional[str]:
    """Classify an email message and return the best matching label key.

    Args:
        message: EmailMessage with metadata (no body).

    Returns:
        Label key string (e.g. 'priority_security') or None if no match.
    """
    subject_lower = message.subject.lower()
    domain = message.domain

    # 1. Social domain check (fastest)
    for soc_domain in _SOCIAL_DOMAINS:
        if soc_domain in domain:
            return "archive_social"

    # 2. Priority domain overrides
    if domain in _PRIORITY_DOMAINS:
        return _PRIORITY_DOMAINS[domain]

    # 3. Followup detection (reply needed)
    if re.match(r"^re:", subject_lower, re.IGNORECASE):
        # Check if from a known contact (not bulk)
        if not message.is_bulk:
            return "followup"

    # 4. Subject keyword matching
    best_match = None
    for category, label_key, patterns in _SUBJECT_RULES:
        for pattern in patterns:
            if re.search(pattern, subject_lower, re.IGNORECASE):
                best_match = label_key
                break
        if best_match:
            break

    if best_match:
        return best_match

    # 5. Bulk/newsletter header detection
    # (headers not available in EmailMessage yet — Phase 2 refinement)
    # For now, fallback to domain-based bulk detection
    if message.is_bulk:
        return "archive_notifications"

    return None


def classify_many(messages: list[EmailMessage]) -> dict[str, list[EmailMessage]]:
    """Classify multiple messages and group by label key.

    Args:
        messages: List of EmailMessage objects.

    Returns:
        dict mapping label_key → list of matching messages.
    """
    result: dict[str, list[EmailMessage]] = {}
    for msg in messages:
        key = classify(msg)
        if key:
            result.setdefault(key, []).append(msg)
    return result
