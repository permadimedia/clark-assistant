# Email Automation Improvements

## Problem Summary

| Issue | Impact |
|-------|--------|
| No email memory: same emails re-scanned daily | Duplicate notifications every scan |
| No new/seen distinction | User can't tell what's actually new |
| No unread prioritization | All emails treated equally in reports |
| No scan audit trail | Can't debug or verify behavior |
| Data coupled to core Clark DB | Violates plugin architecture |

## Solution: Self-Contained Email Module with SQLite

### 1. Data Layer — Separate SQLite Database

**File:** `data/email.db` (not `assistant.db`)

Managed by `EmailDatabase` class in the module. Schema:

```sql
-- email_messages: track every seen email
CREATE TABLE email_messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id      TEXT    NOT NULL,          -- Gmail/IMAP stable ID
    provider        TEXT    NOT NULL DEFAULT 'gmail',
    thread_id       TEXT    DEFAULT '',
    from_email      TEXT    NOT NULL,
    from_name       TEXT    DEFAULT '',
    subject         TEXT    NOT NULL,
    snippet         TEXT    DEFAULT '',
    received_at     TEXT,                      -- ISO-8601
    is_read         INTEGER DEFAULT 0,
    label_key       TEXT    DEFAULT '',         -- classified category
    first_seen_at   TEXT    NOT NULL,           -- first scan that saw this
    last_seen_at    TEXT    NOT NULL,           -- latest scan that saw this
    is_new          INTEGER DEFAULT 1,          -- not yet shown to user
    notified        INTEGER DEFAULT 0,          -- notification sent
    created_at      TEXT    DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- indexing for performance
CREATE UNIQUE INDEX idx_email_msg_id ON email_messages(provider, message_id);
CREATE INDEX idx_email_received ON email_messages(received_at DESC);
CREATE INDEX idx_email_new ON email_messages(is_new, label_key);
CREATE INDEX idx_email_search ON email_messages(from_email, subject);
CREATE INDEX idx_email_seen ON email_messages(first_seen_at DESC);

-- email_scan_log: audit trail
CREATE TABLE email_scan_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    scanned_at      TEXT    NOT NULL,
    total_fetched   INTEGER DEFAULT 0,
    total_new       INTEGER DEFAULT 0,
    total_priority  INTEGER DEFAULT 0,
    total_archived  INTEGER DEFAULT 0,
    classified      TEXT    DEFAULT '{}',      -- JSON summary
    unclassified    INTEGER DEFAULT 0,
    error           TEXT    DEFAULT '',
    duration_ms     INTEGER DEFAULT 0
);
```

### 2. Engine — Updated Scan Flow

```
scan()
  ├── Start timer
  ├── Fetch messages from provider (up to scan_limit)
  ├── For each message:
  │     ├── Check email_messages by message_id
  │     ├── If NEW → INSERT, is_new=1, classify
  │     ├── If EXISTS → UPDATE last_seen_at, is_read, is_new=0
  │     └── Track counts
  ├── Return: { new_messages, seen_messages, summary }
  └── Log to email_scan_log

get_new_notifications()
  ├── Query email_messages WHERE is_new=1 AND notified=0
  ├── Order: priority labels first, then received_at DESC
  └── Return formatted notification text
```

### 3. Formatter — Prioritized Report

```
📬 Email Daily — Hendra, Thu Jun 04

🆕 NEW (3)

  🔒 Security
  from: service@bank.com
  Payment Changed — Today 09:00

  💳 Billing
  from: noreply@jago.com
  Payment to WARUNG ABAH — Yesterday 18:00

📌 OLDER UNREAD (2)

  🏢 Notification
  from: info@bions.id
  Jadwal Live Trading — Mon 01 Jun 09:00

━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
📊 3 new · 2 older unread · 45 read
```

### 4. Targeted Search — Local-First

```
search(keyword)
  ├── Query email_messages WHERE from_email LIKE %keyword%
  │     OR subject LIKE %keyword%
  ├── ORDER BY is_new DESC, label_key (priority first), received_at DESC
  ├── If results found → return formatted (instant, no API call)
  └── If no results → scan() then query again (fallback)
```

### 5. Logging — Both Structured & Stderr

- **Structured:** `email_scan_log` table for every scan
- **Application:** Python logging with email-specific logger
- **Daily summary in scan log:** classified counts, duration, errors

## Implementation Plan

```
Step 1: database.py — EmailDatabase class
    ├── aiosqlite connection, WAL mode, row factory
    ├── init_db(): create tables if not exist
    ├── upsert_message(): INSERT or UPDATE email_messages
    ├── get_new_messages(): is_new=1 AND notified=0
    ├── mark_notified(): set notified=1
    ├── search_messages(): by sender/subject/domain
    ├── log_scan(): INSERT email_scan_log
    └── get_stats(): summary counts for reports

Step 2: Update engine.py
    ├── Integrate EmailDatabase in scan()
    ├── Dedup against previous scans
    ├── Track is_new, first_seen, last_seen
    └── Return structured result with new/seen counts

Step 3: Update formatter.py
    ├── NEW section: only items never seen before
    ├── OLDER UNREAD section: seen but still unread
    └── Summary footer

Step 4: Update routes.py + handler.py
    ├── Targeted search: query local DB first
    ├── Scan endpoint: returns cleaner response
    └── New endpoint: GET /api/email/search?q=keyword

Step 5: Update config
    ├── clark.json.example: add email_automation.db_path
    └── __init__.py: pass db_path to engine
```

## Files Changed

```
NEW   modules/email_automation/database.py    (EmailDatabase class + schema)
MODIFIED  modules/email_automation/engine.py  (integrate DB, dedup, track)
MODIFIED  modules/email_automation/formatter.py  (new/unread sections)
MODIFIED  modules/email_automation/routes.py  (search endpoint)
MODIFIED  modules/email_automation/handler.py (response formatting)
MODIFIED  clark.json.example                  (db_path config)
MODIFIED  modules/email_automation/__init__.py (config wiring)
```
