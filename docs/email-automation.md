# Email Automation Module — Setup Guide

## Privacy & Safety First

This module reads **only metadata** from your inbox:

- Sender name & email address
- Subject line
- Date received
- Snippet/preview (~100 characters)

**No body content, no attachments, no sent messages, no contacts.**

The default scope is `gmail.metadata` (read-only). Write operations (labeling,
archiving, trashing) require explicit opt-in via `read_only: false` in config.

---

## Architecture

```
┌─────────────────────────────────────────────┐
│              EmailEngine                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│  │ Provider │  │Classifier│  │ Formatter│  │
│  │ (Gmail)  │  │ (rules)  │  │ (notify) │  │
│  └──────────┘  └──────────┘  └──────────┘  │
│  ┌──────────────────────────────────────┐   │
│  │          EmailDatabase               │   │
│  │  ~/.clark/email.db (SQLite)         │   │
│  │  Tables: email_messages, scan_log   │   │
│  └──────────────────────────────────────┘   │
└─────────────────────────────────────────────┘
```

Key design decisions:
- **Separate DB** — `~/.clark/email.db` is self-contained, not coupled to core Clark `assistant.db`
- **Dedup by message_id** — same email never notified twice
- **Provider-agnostic** — swap Gmail for IMAP/Outlook by changing one config line
- **Scanner logs audit trail** — every scan logged with duration, counts, errors

---

## Features

### Email Tracking Database

Each scanned email is stored in `email_messages` table:

| Field | Purpose |
|-------|---------|
| `message_id` | Stable Gmail/IMAP ID — key for dedup |
| `is_new` | First time this email appeared |
| `first_seen_at` | When it first appeared |
| `last_seen_at` | Latest scan that saw it |
| `notified` | Notification sent to Telegram |
| `label_key` | Classified category (security, billing, etc.) |

Scan audit log (`email_scan_log`) tracks every scan for debugging:

```
scanned_at, total_fetched, total_new, total_seen,
total_priority, classified (JSON), duration_ms, error
```

### Smart Notifications

Notifications are split into two sections:

```
🆕 NEW — items never seen before (first scan)
📌 OLDER UNREAD — previously seen but still unread
```

Within each section, emails are ordered by priority:
1. 🔒 Security (password changes, 2FA, suspicious activity)
2. 💳 Billing (payments, invoices, tax documents)
3. 👤 User Account (verifications, invitations)
4. 📋 Followup (reply-able threads)
5. 🔔 Notifications / 📢 Promo / 📨 Social / 📰 Newsletter

### Improved Classifier

Classifier rules live in `modules/email_automation/data/classifier_rules.json`
— editable without changing code.

Trained on 50 real inbox emails with support for:
- English + Indonesian keywords (`voucher`, `diskon`, `pembayaran`, `berhasil`, `kode verifikasi`, etc.)
- GitHub security emails (token added, 2FA recovery) correctly classified as `priority_security`
- Sender domain fallbacks (github.com → notifications, medium.com → newsletter)

### Local Search

`GET /api/email/search?q=keyword` queries the local database — instant,
no API call. Falls back to Gmail API scan if no results found locally.

---

## Setup (Gmail)

### Step 1: Create a Google Cloud Project

1. Go to https://console.cloud.google.com/
2. Create a new project (or select existing)
3. Navigate to **APIs & Services → Library**
4. Search for **Gmail API** → Enable

### Step 2: Add Test User (App in Testing Mode)

Since the app is in **Testing** status (not published), you need to add your
Gmail address as a test user:

1. **APIs & Services → OAuth consent screen**
2. Set User Type: **External**
3. Fill required fields (app name, support email, developer contact)
4. **Add Test Users** → add your Gmail address

### Step 3: Create OAuth 2.0 Credentials

1. **APIs & Services → Credentials**
2. Click **Create Credentials → OAuth Client ID**
3. Application type: **Desktop app**
4. Name: `clark-email-automation`
5. Click **Create**
6. Click **Download JSON** → save the file

### Step 4: Save Credentials Locally

```bash
mkdir -p ~/.config/email
mv ~/Downloads/client_secret_*.json ~/.config/email/credentials.json
```

### Step 5: Enable the Module

Add to your `clark.json`:

```json
{
  "modules": {
    "email_automation": {
      "enabled": true,
      "provider": "gmail",
      "credentials_path": "~/.config/email/credentials.json",
      "token_path": "~/.config/email/token.json",
      "db_path": "~/.clark/email.db",
      "scan_schedule": "0 11 * * *",
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

### Step 6: First Run

Restart clark:

```bash
python cli.py restart
```

On the first scan, a browser window will open asking for Gmail consent.
Authenticate with your Google account and grant the requested permissions.

After consent, a token will be saved to `~/.config/email/token.json`
for future use (no re-authentication needed).

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/email/status` | Provider status + DB stats + recent scan history |
| `POST` | `/api/email/scan` | Trigger scan — fetch, classify, dedup, store |
| `GET` | `/api/email/search?q=...` | Search tracked emails by sender/subject (local, instant) |
| `POST` | `/api/email/notified` | Mark pending new emails as notified |
| `POST` | `/api/email/cleanup` | Delete drafts / archive old (read_only must be false) |

### Status Response Example

```json
{
  "provider": "gmail",
  "status": "connected",
  "read_only": true,
  "last_scan_at": "2026-06-03 13:52:07 WIB",
  "stats": {
    "total_tracked": 50,
    "new_unnotified": 0,
    "older_unread": 20,
    "read": 30
  },
  "recent_scans": [
    {
      "scanned_at": "...",
      "fetched": 50,
      "new": 1,
      "seen": 49,
      "priority": 17,
      "duration_ms": 12534
    }
  ]
}
```

### Scan Response Example

```json
{
  "status": "completed",
  "provider": "gmail",
  "total": 50,
  "new": 0,
  "seen": 50,
  "priority_count": 17,
  "classified": {
    "priority_security": 8,
    "priority_billing": 7,
    "priority_user_account": 2,
    "archive_notifications": 19,
    "archive_promo": 9,
    "archive_newsletter": 1,
    "archive_social": 4
  },
  "summary": "📬 Email Daily — ...",
  "last_scan_at": "2026-06-03 13:52:07 WIB"
}
```

---

## Notification Format

Daily scan notifications follow this structure (Telegram-friendly):

```
📬 Email Daily — Hendra, Wed, Jun 03, 2026

🆕 NEW — 3 emails

  🔒 Security
  from: Service
  Password changed notification
  📅 Today 09:00


📌 OLDER UNREAD — 5 emails

  💳 Billing
  from: Bank Jago
  Payment to WARUNG ABAH
  📅 Yesterday 18:21

━━━━━━━━━━━━━━━━━━━━━━━━━
📊 3 new · 5 unread · 42 read
Last scan: Wed 13:52 WIB

📌 /scan to refresh · /email search [keyword]
🦊 <i>clark</i>
```

Rules:
- Plain text, no HTML tables
- Grouped by label category (security, billing, etc.)
- Priority ordering within each section
- Summary footer with counts
- Emoji markers: 🆕 new, 📌 older unread, 🔒 security, 💳 billing

---

## Agent Integration

When an agent queries emails, they should:

1. Call `POST /api/email/scan` to fetch latest inbox
2. Use `GET /api/email/search?q=keyword` for targeted queries (instant)
3. Present results with the approved format (see clark skill)
4. Call `POST /api/email/notified` after presenting to mark as notified

---

## Configuration Reference

| Key | Default | Description |
|-----|---------|-------------|
| `enabled` | `false` | Enable the module |
| `provider` | `"gmail"` | Email provider type (gmail / future: imap, outlook) |
| `credentials_path` | `~/.config/email/credentials.json` | OAuth client ID JSON |
| `token_path` | `~/.config/email/token.json` | OAuth token storage |
| `db_path` | `~/.clark/email.db` | SQLite database for email tracking |
| `scan_schedule` | `"0 7 * * *"` | Cron expression for daily scan |
| `scan_limit` | `50` | Max emails per scan |
| `chat_id` | `0` | Telegram chat ID for notifications |
| `labels_enabled` | `true` | Apply Gmail labels (requires write mode) |
| `archive_read_after_days` | `90` | Auto-archive read after N days |
| `trash_draft_after_days` | `30` | Delete drafts older than N days |
| `read_only` | `true` | Read-only mode (no labeling, no archiving) |

---

## Security Notes

- **Token files are private**: Never share `~/.config/email/token.json`.
  It's an OAuth token that grants access to your email metadata.
- **Revoke access anytime**: Visit https://myaccount.google.com/permissions
  → Revoke `clark-email-automation`.
- **Credentials & tokens are not in git**: Stored outside the repository.
- **Start read-only**: The default is `read_only: true`. Only messages are
  fetched, never modified. Change to `false` only when you're ready for
  auto-labeling and archiving.

---

## Troubleshooting

| Problem | Likely Cause | Solution |
|---------|-------------|----------|
| `401: Bad Credentials` | Token expired | Delete `~/.config/email/token.json` and re-authenticate |
| `missing credentials` | No credentials file | Complete setup steps above |
| `missing dependencies` | Google libs not installed | `pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib` |
| No notifications | chat_id not set | Set `chat_id` in config to your Telegram chat ID |
| Disk I/O error on DB | Filesystem issue | Ensure `~/.clark/` is writable; try `PRAGMA journal_mode=DELETE` |
