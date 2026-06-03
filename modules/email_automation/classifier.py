"""Rule-based email classifier — no ML, no external APIs.

Classification uses only metadata (from_email, subject, headers).
No body content is ever accessed.

Rules are loaded from data/classifier_rules.json — edit that file to
customize detection without changing code.
"""

import json
import logging
import re
from pathlib import Path
from typing import Optional

from modules.email_automation.providers.base import EmailMessage
from modules.email_automation.labels import LABELS, LabelDef

logger = logging.getLogger(__name__)

# ── Load rules from data file ──────────────────────────────

_RULES_PATH = Path(__file__).resolve().parent / "data" / "classifier_rules.json"

_rules: dict | None = None


def _load_rules() -> dict:
    """Load rules from classifier_rules.json. Falls back to empty dict on error."""
    global _rules
    if _rules is not None:
        return _rules

    try:
        if _RULES_PATH.exists():
            _rules = json.loads(_RULES_PATH.read_text())
            logger.info("Loaded classifier rules from %s (%d subject rules, %d social domains)",
                        _RULES_PATH,
                        len(_rules.get("subject_rules", [])),
                        len(_rules.get("social_domains", [])))
        else:
            logger.warning("Classifier rules file not found at %s, using empty defaults", _RULES_PATH)
            _rules = {
                "social_domains": [],
                "priority_domains": {},
                "bulk_headers": [],
                "subject_rules": [],
            }
    except Exception as e:
        logger.error("Failed to load classifier rules: %s", e)
        _rules = {
            "social_domains": [],
            "priority_domains": {},
            "bulk_headers": [],
            "subject_rules": [],
        }

    return _rules


def reload_rules() -> None:
    """Force-reload rules from disk (useful after hot-edit)."""
    global _rules
    _rules = None
    _load_rules()
    logger.info("Classifier rules reloaded from %s", _RULES_PATH)


def _social_domains() -> list[str]:
    return _load_rules().get("social_domains", [])


def _priority_domains() -> dict[str, str]:
    return _load_rules().get("priority_domains", {})


def _subject_rules() -> list[dict]:
    return _load_rules().get("subject_rules", [])


# ── Core classification ────────────────────────────────────


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
    for soc_domain in _social_domains():
        if soc_domain in domain:
            return "archive_social"

    # 2. Priority domain overrides
    if domain in _priority_domains():
        return _priority_domains()[domain]

    # 3. Followup detection (reply needed)
    if re.match(r"^re:", subject_lower, re.IGNORECASE):
        if not message.is_bulk:
            return "followup"

    # 4. Subject keyword matching
    for rule in _subject_rules():
        label_key = rule.get("label_key", "")
        patterns = rule.get("patterns", [])
        for pattern in patterns:
            try:
                if re.search(pattern, subject_lower, re.IGNORECASE):
                    return label_key
            except re.error:
                logger.warning("Invalid regex pattern: '%s' in rule '%s'", pattern, label_key)
                continue

    # 5. Bulk sender fallback
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
