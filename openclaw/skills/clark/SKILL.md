---
name: clark
description: Use clark REST API (localhost:8124) for reminders, agenda, notes, and scheduling tasks.
user-invocable: false
---

# clark — Your Right Hand

clark is a lightweight REST API backend running on `localhost:8124` that handles
reminders, agenda, notes, and scheduling. It sends notifications via Telegram.

## Agent Boot Cycle

On **every session start** (wakeup, restart, heartbeat):

```bash
# Step 1: Check if clark is alive
python cli.py status

# Step 2: Start if dead
python cli.py start

# Step 3: Verify healthy
curl -sf http://localhost:8124/api/health
```

If clark was down during a scheduled reminder, it auto-recovers on startup
and fires missed reminders — no manual intervention needed.

## Behavioral Rules

These rules are **not optional**. Follow them every time you use clark.

### 1. Max 3 Exec Calls Per Turn

Do not silently chain >3 tool calls. If a task needs more:
- Batch independent calls into one exec (e.g., multiple `curl` commands in one shell script)
- Or explain what you'll do and get approval before proceeding

### 2. Clarify Before Execute

If **any** parameter is ambiguous (lead time? save as note? format?), ask first.
Do not assume defaults unless the user explicitly accepted them before.

### 3. Telegram-Friendly Formatting

When presenting clark data to users (especially on Telegram, WhatsApp, Discord):

- **No markdown tables** — use bullet lists instead
- **No code blocks** for agenda/reminder output — format inline
- **Scannable** — group by time, use emoji markers (⏰ 📋 👥 🏢)
- **Never dump raw JSON** — reformat into readable text

Good:
```
⏰ 09.00 — Daily Standup
👥 Engineering Team
🏢 Online
```

Bad:
```
| Time | Event | Participants |
| 09:00 | Daily Standup | Engineering Team |
```

### 4. Check Before Use

Always verify clark is healthy before calling its API:
```bash
python cli.py status   # or ./status-clark.sh
```
Only proceed if status shows `API: healthy`.

### 5. Config Does Not Create Jobs

**`clark.json` is for runtime settings only** (token, module toggles, DB path).
It does **not** auto-create scheduled jobs.

To set up recurring agenda delivery, you must explicitly create cron jobs
via the Scheduler API:

```bash
# Morning agenda (06:00 WIB) — today's agenda
curl -X POST http://localhost:8124/api/scheduler/jobs \
  -H "Content-Type: application/json" \
  -d '{"name":"Agenda Pagi","job_type":"send_agenda","schedule_type":"cron","schedule_config":{"cron":"0 6 * * *","tz":"Asia/Jakarta"},"payload":{"chat_id":123456789,"range":"today"}}'

# Evening agenda (16:00 WIB) — tomorrow's agenda
curl -X POST http://localhost:8124/api/scheduler/jobs \
  -H "Content-Type: application/json" \
  -d '{"name":"Agenda Sore","job_type":"send_agenda","schedule_type":"cron","schedule_config":{"cron":"0 16 * * *","tz":"Asia/Jakarta"},"payload":{"chat_id":123456789,"range":"tomorrow"}}'
```

Once created, these jobs persist in the database and run forever —
the agent does not need to recreate them on every session.

## API Reference

Base URL: `http://localhost:8124`

### Reminders

```bash
POST /api/reminders
{
  "text": "Meeting at 14:00\n👥 John, Sarah",
  "time": "2026-06-02T14:00:00+07:00",
  "alert_before_minutes": 10    # default 10, 0 = at event time
}
# → Auto-creates scheduler job at (time - alert_before_minutes)

GET  /api/reminders             # list active (unfired)
GET  /api/reminders?fired=true  # list fired
DELETE /api/reminders/{id}
```

### Agenda

```bash
GET /api/agenda?range=today      # today's agenda
GET /api/agenda?range=tomorrow   # tomorrow
GET /api/agenda?range=week       # this week
```

### Notes

```bash
POST /api/notes          {"text": "..."}
GET  /api/notes/search   ?q=keyword
GET  /api/notes
PUT  /api/notes/{id}
DELETE /api/notes/{id}
```

### Scheduler (Scheduled Jobs)

```bash
POST /api/scheduler/jobs
{
  "name": "Daily agenda",
  "job_type": "send_agenda",
  "schedule_type": "cron",
  "schedule_config": {"cron": "0 6 * * *", "tz": "Asia/Jakarta"},
  "payload": {"chat_id": 123456789, "range": "today"}
}

GET    /api/scheduler/jobs
POST   /api/scheduler/jobs/{id}/trigger   # fire immediately
DELETE /api/scheduler/jobs/{id}
```

**Job types:**
- `send_message` → send arbitrary text via Telegram
- `send_agenda` → send agenda summary via Telegram
- `reminder_alert` → fire a stored reminder (auto-created by POST /api/reminders)
- `email_daily_scan` → scan inbox, classify, and notify (see Email Automation below)

**Schedule types:**
- `cron` → `{"cron": "0 6 * * *", "tz": "Asia/Jakarta"}`
- `once` → `{"at": "2026-06-02T09:00:00+07:00"}`
- `interval` → `{"interval_minutes": 30}`

### Email Automation (Gmail / IMAP)

Email module reads **only metadata** (from, subject, date, snippet).
No body content, no attachments, no sent messages.

```bash
# Check connection & last scan status
GET /api/email/status

# Trigger instant scan → classify → notify Telegram
POST /api/email/scan

# Execute cleanup: archive old emails, delete old drafts
POST /api/email/cleanup
```

**Agent rules for email:**
1. Always call `POST /api/email/scan` fresh when user asks — don't rely on cached data.
2. Filter results using a targeted Python script — parse sender, subject, date from the inbox.
3. Respect read-only mode: don't offer cleanup/delete unless user explicitly asks.
4. Default scope is `gmail.metadata` — no body content available.
5. **Never** commit email credentials or tokens to git — credentials live at `~/.config/email/`.

**Approved reporting format (Telegram-friendly):**

When user asks about specific emails, present results like this:

```
📬 Email Query — [Search Keyword]

🏢 [Company Name] — N email found

• Sender Name
  Subject line in full, never truncated
  📅 Day Date, Time

• Sender Name
  Subject line in full, never truncated
  📅 Day Date, Time

💻 Another Company — No results
```

Rules for the report:
- **No markdown tables** — use bullet lists with indentation
- **No code blocks** for the email content — plain text
- **Sender name** italic or plain, never bold
- **Subject** full, never truncated
- Group by sender/domain when multiple emails from same source
- Use emoji sparingly: 📬 header, 🏦 finance, 💻 tech, 🏢 company, 📅 date
- If no results: "[Keyword] — No results" — simple, no fuss
- **Never use real user data** in the template — use generic placeholders (e.g. "Sender Name", "Company Name")

**Daily scheduled scan:**
```bash
# Register once (persists in DB):
curl -X POST http://localhost:8124/api/scheduler/jobs \
  -H "Content-Type: application/json" \
  -d '{"name":"Email Daily Scan","job_type":"email_daily_scan","schedule_type":"cron","schedule_config":{"cron":"0 11 * * *","tz":"Asia/Jakarta"},"payload":{"chat_id":123456789,"scan_limit":50}}'
```

**Safety rules for agent:**
- **Never** read or expose full email body content (not available anyway)
- **Never** commit email credentials or tokens to git
- Credentials live at `~/.config/email/` outside repo
- Cleanup actions (`/cleanup`) only if user explicitly asks

### Config & Health

```bash
GET  /api/health                 # basic health
GET  /api/health/detailed        # module status
GET  /api/modules                # list modules
POST /api/reload                 # reload clark.json config changes
```

### Scaffolding (Creating New Modules)

```bash
# CLI (no server needed):
python cli.py make module --name weather --desc "Forecast" --with-handler

# Or API (server required):
POST /api/modules/scaffold   {"name": "weather"}
```

## Module-Specific Behaviors

### Email Automation

The `email_automation` module scans Gmail inbox metadata and sends a
smart daily notification to Telegram. It also supports on-demand queries
when the user asks about specific emails.

**Provider-agnostic:** Current implementation uses Gmail API with `gmail.metadata`
scope. Future: IMAP, Outlook Graph, Proton Bridge.

**Label strategy (when write mode is enabled):**

| Priority (visible in inbox) | Archive (skip inbox) |
|---------------------------|---------------------|
| `!Priority/Security` | `_Archive/Promo` |
| `!Priority/Billing` | `_Archive/Newsletter` |
| `!Priority/User-Account` | `_Archive/Social` |
| `!Followup` | `_Archive/Notifications` |

**Config in `clark.json`:**
```json
{
  "modules": {
    "email_automation": {
      "enabled": true,
      "provider": "gmail",
      "credentials_path": "~/.config/email/credentials.json",
      "token_path": "~/.config/email/token.json",
      "scan_schedule": "0 11 * * *",
      "scan_limit": 50,
      "chat_id": 0,
      "read_only": true
    }
  }
}
```

## Reminder Format

Telegram notifications show:
```
🔔 Title of Reminder           ← first line bold only
Details, participants, notes  ← normal weight
⏰ 14:00
━━━━━━━━━━━━━━━━
🦊 clark                       ← footer
```

Only the first line is bold. Details, location, participants display as normal text.

## Related Docs

- [Agent Integration Guide](docs/agent-integration.md) — full workflow reference
- [Coding Philosophy](docs/coding-philosophy.md) — framework design principles
