#!/usr/bin/env python3
"""Verify email_automation module — imports, classifier, formatter, provider base."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

passed = 0
failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        print(f"  ✅ {name}")
        passed += 1
    else:
        print(f"  ❌ {name} — {detail}")
        failed += 1


# ── 1. Module class ────────────────────────────────────────

print("\n1️⃣  Module class & definitions")

from modules.email_automation import EmailAutomationModule
check("EmailAutomationModule exists", hasattr(EmailAutomationModule, "name"))
mod = EmailAutomationModule()
check("Module name = email_automation", mod.name == "email_automation")
check("Has engine property", hasattr(mod, "engine"))
check("Has job_handlers", "email_daily_scan" in mod.job_handlers)
check("Has config_defaults", len(mod.config_defaults) > 0)
check("Read-only by default", mod.config_defaults["read_only"] == True)

# ── 2. Provider base ───────────────────────────────────────

print("\n2️⃣  Provider base class")

from modules.email_automation.providers.base import EmailProvider, EmailMessage
check("EmailProvider is abstract", EmailProvider.__abstractmethods__ is not None)
check("EmailMessage has metadata-only fields", hasattr(EmailMessage, "from_email"))
check("EmailMessage has NO body", not hasattr(EmailMessage, "body"))
check("EmailMessage has NO attachments content", not hasattr(EmailMessage, "attachment_data"))
check("EmailMessage.domain works", EmailMessage(id="1", from_email="test@gmail.com").domain == "gmail.com")

# ── 3. Gmail provider ──────────────────────────────────────

print("\n3️⃣  Gmail provider")

from modules.email_automation.providers.gmail import GmailProvider, SCOPE_METADATA, SCOPE_MODIFY
check("SCOPE_METADATA correct", "gmail.metadata" in SCOPE_METADATA)
check("SCOPE_MODIFY correct", "gmail.modify" in SCOPE_MODIFY)

gp = GmailProvider(credentials_path="~/.config/email/credentials.json",
                   token_path="~/.config/email/token.json", read_only=True)
check("GmailProvider inherits EmailProvider", isinstance(gp, EmailProvider))
check("Status starts disconnected", gp.status == "disconnected")

# ── 4. Labels ──────────────────────────────────────────────

print("\n4️⃣  Label definitions")

from modules.email_automation.labels import LABELS, get_label, priority_labels, archive_labels
check("Has all 10 labels", len(LABELS) == 10)
check("Priority labels exist", len(priority_labels()) >= 4)
check("Archive labels exist", len(archive_labels()) >= 4)
check("!Prefix for priority", get_label("priority_security").name.startswith("!"))
check("_Prefix for archive", get_label("archive_promo").name.startswith("_"))

# ── 5. Classifier ──────────────────────────────────────────

print("\n5️⃣  Classifier")

from modules.email_automation.classifier import classify, classify_many
from modules.email_automation.providers.base import EmailMessage

# Security email
msg = EmailMessage(id="1", from_email="security@bank.com",
                   subject="Your account password has been changed")
check("Classifies security email", classify(msg) == "priority_security")

# Billing email
msg2 = EmailMessage(id="2", from_email="billing@aws.com",
                     subject="AWS Invoice — USD 43.21")
check("Classifies billing email", classify(msg2) == "priority_billing")

# Account email
msg3 = EmailMessage(id="3", from_email="noreply@shopify.com",
                     subject="Welcome to Shopify! Verify your email")
check("Classifies account email", classify(msg3) == "priority_user_account")

# Social email
msg4 = EmailMessage(id="4", from_email="notification@facebookmail.com",
                     subject="Someone liked your photo")
check("Classifies social (facebookmail) email", classify(msg4) == "archive_social")

# Promo email
msg5 = EmailMessage(id="5", from_email="marketing@store.com",
                     subject="50% OFF — Don't miss this deal!"),
check("Classifies promo email", classify(msg5[0] if isinstance(msg5, tuple) else msg5) == "archive_promo")

# Follow-up (Re:)
msg6 = EmailMessage(id="6", from_email="rekan@project.com",
                     subject="Re: Meeting Notes — Proposal Q3")
check("Classifies followup email", classify(msg6) == "followup")

# Unknown email
msg7 = EmailMessage(id="7", from_email="friend@personal.com",
                     subject="Hey! How are you?")
check("Unknown email returns None", classify(msg7) is None)

# classify_many
results = classify_many([msg, msg2, msg3, msg4, msg5[0] if isinstance(msg5, tuple) else msg5, msg6, msg7])
check("classify_many returns dict", isinstance(results, dict))
check("Has all expected categories", all(k in results for k in ["priority_security", "priority_billing", "priority_user_account", "archive_social", "archive_promo", "followup"]))

# ── 6. Formatter ───────────────────────────────────────────

print("\n6️⃣  Formatter")

from modules.email_automation.formatter import format_daily_summary
from datetime import datetime, timezone, timedelta

msgs = [
    EmailMessage(id="1", from_email="security@bank.com", subject="Password changed",
                 snippet="Your password was updated", received_at=datetime.now(timezone.utc)),
    EmailMessage(id="2", from_email="promo@shop.com", subject="50% OFF everything!",
                 snippet="Limited time offer", received_at=datetime.now(timezone.utc)),
]
classified = {
    "priority_security": [msgs[0]],
    "archive_promo": [msgs[1]],
}

summary = format_daily_summary(msgs, classified, user_name="TestUser")
check("Formatter returns string", isinstance(summary, str))
check("Contains user greeting", "TestUser" in summary)
check("Contains priority header", "PRIORITY" in summary)
check("Contains sender info", "security@bank.com" in summary)
check("Contains subject", "Password changed" in summary)
check("Contains clark footer", "clark" in summary)

# ── 7. Engine ──────────────────────────────────────────────

print("\n7️⃣  Engine")

from modules.email_automation.engine import EmailEngine
engine = EmailEngine(provider_type="gmail", read_only=True)
check("Engine created", engine is not None)
check("Provider type = gmail", engine.provider_type == "gmail")
check("Read-only = True", engine.read_only == True)
check("Provider not connected yet", engine.provider is None)
check("Last scan is None", engine.last_scan_at is None)

# Empty result
result = engine._empty_result("test")
check("Empty result format", result["total"] == 0)
check("Empty result has summary", "test" in result["summary"])

# ── Summary ─────────────────────────────────────────────────

total = passed + failed
print(f"\n{'='*40}")
print(f"   {passed}/{total} passed")
if failed:
    print(f"   {'❌' * failed} {failed} FAILURES")
    sys.exit(1)
else:
    print(f"   ✅ All tests passed!")
    print(f"\nModule is ready for integration testing with Gmail API.\n"
          f"Next: configure credentials in ~/.config/email/credentials.json\n"
          f"and set chat_id in clark.json, then start clark.")
