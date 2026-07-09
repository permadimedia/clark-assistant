# Email Automation Module — Proposal

> **Status:** ✅ Approved · Phase 1 in progress (`feat/email-automation`)
> **Authors:** permadimedia · OpenClaw

---

## Overview

A provider-agnostic email automation module for clark-assistant. Organizes your inbox,
declutters low-priority messages, flags important ones (security, billing, user
accounts), and sends a daily smart notification via Telegram — using only metadata
(from, subject, date, snippet) for maximum privacy.

---

## Architecture

```
                    ┌──────────────────────────────┐
                    │       Email Engine           │
                    │  classify → label → notify   │
                    └──────┬──────────┬──────┬─────┘
                           │          │      │
                      ┌────▼────┐ ┌──▼───┐ ┌─▼────┐
                      │  Gmail  │ │ IMAP │ │ ...  │
                      │  (API)  │ │(Generic│ │Future│
                      └─────────┘ └──────┘ └──────┘
```

### Integration With Clark

```
Clark Engine
  ├── Scheduler (daemon loop)
  │     └── cron "0 7 * * *" → trigger "email_daily_scan" handler
  ├── Handler: email_daily_scan
  │     ├── provider.list_metadata(limit=50)   ← only from/subject/date/snippet
  │     ├── engine.classify(messages)          ← rule-based, no body content
  │     ├── provider.apply_labels(messages)    ← only with write scope enabled
  │     ├── engine.generate_summary()          ← smart notification
  │     └── notifier.send_message(summary)     ← Telegram
  └── API: /api/email/*
        ├── GET  /status        → last scan info + stats
        ├── POST /scan          → trigger scan now
        └── POST /cleanup       → execute archive/trash (with confirmation)
```

### Resource Profile

| State | RAM | CPU | Duration |
|-------|-----|-----|----------|
| Idle | ~0 MB (shared with Clark) | ~0% | 23h 59m |
| Scanning | ~20–40 MB peak | Low (I/O bound) | ~30–60s |
| **Daily total** | — | < 1 min CPU | — |

---

## Label Strategy

| Label | Scope | Action |
|-------|-------|--------|
| `!Priority/Security` | Security alerts, 2FA, login changes, password resets | Flag + Notify |
| `!Priority/Billing` | Invoices, payment receipts, subscriptions | Flag + Notify |
| `!Priority/User-Account` | Signups, verifications, account actions | Flag + Notify |
| `!Followup` | Emails from known contacts needing reply | Flag + Notify |
| `_Archive/Promo` | Promotions, deals, offers | Auto-archive |
| `_Archive/Newsletter` | Newsletters, blog digests | Auto-archive |
| `_Archive/Social` | LinkedIn, Twitter, Facebook notifications | Auto-archive |
| `_Archive/Notifications` | System/transactional notifications | Auto-archive |
| `_Trash/Old-Drafts` | Empty drafts > 30 days | Suggest delete |
| `_Trash/Read-Archived` | Read emails > 90 days | Suggest archive |

Prefix convention: `!` = visible in inbox, `_` = archive (skip inbox).

---

## Data Privacy

### Scope — Minimal by Design

| Data | Accessed | Purpose |
|------|----------|---------|
| From (name + email) | ✅ Yes | Identify sender |
| Subject line | ✅ Yes | Classify & notify |
| Date received | ✅ Yes | Age-based decisions |
| Snippet/preview (~100 chars) | ✅ Yes | Smart notification context |
| Full body content | ❌ **No** | Not needed |
| Attachments | ❌ **No** | Not needed |
| Contact list | ❌ **No** | Not needed |
| Sent messages | ❌ **No** | Inbox only |

### Credential Storage

All credentials stored **outside the repo**, under the user's home directory:

```
~/.config/email/
├── credentials.json     ← Provider credentials (OAuth client ID or IMAP password)
└── token.json           ← OAuth token (auto-generated on first consent)
```

These paths are configurable via `clark.json` and never committed to git.

### Gmail API Scopes

```
Minimal (default):    https://www.googleapis.com/auth/gmail.metadata
                      → Read metadata only — no body, no attachments

Extended (optional):  https://www.googleapis.com/auth/gmail.modify
                      → Label, archive, trash — still no body content
```

Users can choose to stay in **read-only mode indefinitely** (receive notifications
without auto-labeling/archiving).

---

## Classification Engine

Rule-based, no ML, no external API calls. Classification uses:

| Category | Detection Rules |
|----------|----------------|
| 🔒 Security | `subject` matches: password, login, 2FA, security, suspicious, verified, authentication, sign-in, breach, alert, blocked |
| 💳 Billing | `subject` matches: invoice, receipt, payment, bill, subscription, tagihan, billing, transaction, statement, receipt |
| 👤 User Account | `subject` matches: welcome, registered, verification, account, sign up, activation, confirm, onboarding |
| 📋 Followup | Email has `In-Reply-To` header OR `subject` starts with `Re:` AND sender is in contacts |
| 📢 Promo | `List-Unsubscribe` header present OR `subject` matches: promo, discount, sale, offer, deal, coupon, save |
| 🗞️ Newsletter | `List-Id` header present OR `Precedence: bulk` OR `X-Mailer: mailchimp` / `sendgrid` / `ses` |
| 👥 Social | `from_email` domain matches: facebook, linkedin, twitter/x, instagram, tiktok, youtube, github, medium |
| 🔔 Notifications | `subject` matches: notification, alert, update, status, delivery, tracking, no-reply, noreply |

The `from_email` domain + header-based checks are done first (fastest), then
keyword matching on subject.

---

## Notification Format

```
📬 Email Daily — Hendra, Thu Jun 4 2026
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

! PRIORITY — Action Required

  🔒 Security
  ─────────────────────────────
  from: security@alibaba.com
  subject: Your account will expire in 7 days
  → "Your Alibaba Cloud account is scheduled to..."
  🏷️ → !Priority/Security

  💳 Billing
  ─────────────────────────────
  from: billing@aws.amazon.com
  subject: AWS Invoice — USD 43.21
  → "Your invoice for June 2026 is now available..."
  🏷️ → !Priority/Billing

📋 FOLLOWUP — Needs Reply
  ─────────────────────────────
  from: rekan@project.com
  subject: Re: Meeting Notes — Proposal Q3
  → "Mohon review before 3 PM..."
  ⏳ Unreplied for 3 days

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 Summary:
  • 12 new emails (8 unread, 4 read)
  • 30 promo/newsletters → auto-archived (_Archive)
  • 5 empty drafts expired > 30 days
  • Storage used: 2.1 GB / 15 GB

📌 Reply /cleanup to execute archive & draft cleanup
🦊 clark
```

---

## Configuration

In `clark.json`:

```json
{
  "modules": {
    "email_automation": {
      "enabled": true,
      "provider": "gmail",
      "credentials_path": "~/.config/email/credentials.json",
      "token_path": "~/.config/email/token.json",
      "scan_schedule": "0 7 * * *",
      "scan_limit": 50,
      "chat_id": 76465160,
      "labels_enabled": true,
      "archive_read_after_days": 90,
      "trash_draft_after_days": 30,
      "read_only": true
    }
  }
}
```

---

## Implementation Plan

| Phase | Scope | Mode |
|-------|-------|------|
| **Phase 1** | Module structure + Gmail provider (auth + metadata read) | 🔒 Read-only |
| **Phase 2** | Engine classify + label strategy | 🔒 Read-only |
| **Phase 3** | Scheduler handler + daily Telegram notification | 🔒 Read-only |
| **Phase 4** | Auto-archive, auto-trash (write operations) | ⚠️ Write (opt-in) |
| **Phase 5** | IMAP provider + extensibility docs | 🔒 Read-only |

---

## Module Structure

```
modules/email_automation/
├── __init__.py           ← GmailAutomationModule class
├── routes.py             ← API endpoints (/api/email/*)
├── handler.py            ← Scheduler job handler (daily scan)
├── engine.py             ← Core engine (classify → label → summarize)
├── providers/
│   ├── base.py           ← Abstract EmailProvider interface
│   └── gmail.py          ← Gmail API implementation
├── labels.py             ← Label definitions & strategy
├── classifier.py         ← Rule-based email classifier
└── formatter.py          ← Telegram notification formatter

docs/email-automation.md  ← Setup guide & safety instructions
```
