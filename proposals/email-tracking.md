# Email Tracking & Scan History — Proposal

## Problem

Today, every scan fetches 50 inbox emails and classifies all of them —
including emails already seen in previous scans. No memory of what's
"new" vs "already notified". Notifications repeat the same emails daily.

## Solution: Email Message Tracking

Add two tables to Clark's existing SQLite database (`data/assistant.db`):

### Table 1: `email_messages` — Track Every Seen Email

```sql
CREATE TABLE IF NOT EXISTS email_messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id      TEXT    NOT NULL,       -- Gmail/IMAP stable message ID
    provider        TEXT    NOT NULL,       -- 'gmail', 'imap', etc.
    from_email      TEXT    NOT NULL,
    from_name       TEXT    DEFAULT '',
    subject         TEXT    NOT NULL,
    snippet         TEXT    DEFAULT '',      -- preview ~100 chars
    received_at     TEXT,                    -- ISO-8601 timestamp
    is_read         INTEGER DEFAULT 0,
    label_key       TEXT    DEFAULT '',      -- classified category
    first_seen_at   TEXT    NOT NULL,        -- first time this email appeared
    last_seen_at    TEXT    NOT NULL,        -- last time this email appeared
    notified        INTEGER DEFAULT 0,       -- has notification been sent
    is_new          INTEGER DEFAULT 1,       -- new since last user check
    created_at      TEXT    DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_email_msg_id ON email_messages(provider, message_id);
CREATE INDEX IF NOT EXISTS idx_email_received ON email_messages(received_at DESC);
CREATE INDEX IF NOT EXISTS idx_email_new ON email_messages(is_new, label_key);
CREATE INDEX IF NOT EXISTS idx_email_seen ON email_messages(first_seen_at);
```

### Table 2: `email_scan_log` — Audit Trail

```sql
CREATE TABLE IF NOT EXISTS email_scan_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    scanned_at      TEXT    NOT NULL,
    total_fetched   INTEGER DEFAULT 0,
    total_new       INTEGER DEFAULT 0,      -- first time seeing these
    total_priority  INTEGER DEFAULT 0,
    total_archived  INTEGER DEFAULT 0,
    classified      TEXT    DEFAULT '{}',    -- JSON: {"priority_security": 2, ...}
    error           TEXT    DEFAULT '',
    duration_ms     INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_scan_time ON email_scan_log(scanned_at DESC);
```

## How It Works

### Scan Flow (Updated)

```
1. Fetch inbox messages (50) from Gmail API
2. For each message:
   ├── message_id exists in email_messages?
   │    ├── Yes → update last_seen_at, mark is_new=0
   │    └── No  → INSERT new record (is_new=1, notified=0)
   ├── Classify → store label_key
   └── Track if first time seeing it → total_new++
3. Generate notification:
   ├── FILTER: is_new=1  (never seen before)
   ├── ORDER: priority label first, then unread, then recent
   └── After sending → mark notified=1
4. INSERT scan_log record
```

### Notification Logic (Improved)

```
📬 Email Daily — Hendra, Thu Jun 04 2026

🆕 NEW since last scan (3 emails)                ← only new ones

  🔒 Security
  from: security@bank.com
  subject: Password changed
  📅 Today 09:00

📌 UNREAD from earlier (5 emails)                 ← seen but unread

  💳 Billing
  from: noreply@jago.com
  subject: Payment to WARUNG ABAH
  📅 Yesterday 18:21

━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
📊 Summary
  • 3 new, 5 unread older, 42 already read
  • Last scan: Today 11:00
  • Total tracked: 847 messages
```

### Targeted Query (Improved)

When user asks "any email from BNI?":

```
1. Query email_messages WHERE from_email LIKE '%bni%'
   OR subject LIKE '%bni%'
2. ORDER BY is_new DESC, received_at DESC
3. Show: new items first (🆕), then recent
```

### Data Volume Estimates

| Timeframe | Scans | Messages Tracked | DB Size |
|-----------|-------|-----------------|---------|
| Per scan | — | ~50 fetched, ~10-20 new | ~10 KB |
| Per day | 2-3 | ~30-60 new | ~50 KB |
| Per month | ~90 | ~1,500 new | ~3 MB |
| Per year | ~1,095 | ~18,000 new | ~36 MB |

SQLite handles millions of rows without issue. At 18K/year, this is negligible.

## Migration (Number: 013)

File: `migrations/013_email_tracking.sql`

## Benefits Summary

| Problem | Before | After |
|---------|--------|-------|
| Same email repeated daily | ❌ Yes | ✅ Once, then skip |
| Know what's "new" | ❌ No | ✅ is_new flag |
| Prioritize unread | ❌ No | ✅ ORDER BY is_new, is_read, received_at |
| Search history | ❌ Re-scans API | ✅ Query local DB (instant) |
| Scan audit trail | ❌ None | ✅ email_scan_log table |
| Track classification accuracy | ❌ No | ✅ Historical label_key |
