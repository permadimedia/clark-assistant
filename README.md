# clark

> **Ask clark.** — AI agent backend API for menial tasks.

Reminders · Notes · Agenda · Scheduler · Telegram notifications

**Version:** v0.6.0 | **Idle RAM:** ~100 MB | **Stack:** Python 3.11+ · FastAPI · SQLite · aiosqlite · httpx | **Platform:** Raspberry Pi

```
Sangkuni: "Let me ask clark to create a reminder."
           POST /api/reminders { text: "Meeting 10:00", time: "10:00" }

Sangkuni: "Let me clark that note."
           POST /api/notes { text: "Meeting notes from standup"

Sangkuni: "I'll ask clark about your agenda."
           GET /api/agenda?range=today
```

---

## What It Is

Clark is your AI's desk clerk — a REST API backend that handles menial tasks so AI agents (like OpenClaw assistants) can focus on reasoning and decisions.

> *Clark does no AI. Clark just does the boring work.*

### What It Does

| Feature | What For |
|---------|----------|
| **Reminders** | Create one-shot reminders → fired via Telegram at scheduled time |
| **Agenda** | Query today/tomorrow/week agenda from saved reminders |
| **Notes** | Save, search (FTS5), update, delete reference notes |
| **Scheduler** | Cron/interval/once jobs — `send_message`, `send_agenda`, extensible |
| **Notifier** | Sends Telegram messages via Bot API |
| **Module system** | Self-contained feature modules with auto-discovery |
| **Email Automation** | Scan Gmail metadata, classify, dedup, notify via Telegram (read-only by default) |

### What It Is NOT

- ❌ Not a Telegram bot (no webhook, no gateway)
- ❌ Not an AI/LLM service (the agent calls this, not the other way around)
- ❌ Not a general-purpose web app
- ❌ Not a replacement for your brain (clark just remembers what you'd forget)

---

### Config: One File

All settings in `clark.json`. No `.env`. No scattered config. Editable by humans and agents.

### Modules: Scaffold in Seconds

```bash
# CLI for humans
python cli.py make module --name weather --desc "Daily forecast" --with-handler

# Or API for agents
curl -X POST /api/modules/scaffold -d '{"name": "weather"}'
```

Three files created, clark.json updated, ready to edit.

### Hot Reload: No Restart Needed

`POST /api/reload` applies config changes without interrupting running modules.

---

## Quick Start

### 1. Get a Telegram Bot Token

Talk to [@BotFather](https://t.me/BotFather) on Telegram → `/newbot` → save the token.

### 2. Configure

```bash
cd clark-assistant
cp clark.json.example clark.json
chmod 600 clark.json
# Edit clark.json — fill in telegram.token at minimum
```

### 3. Run

```bash
uv sync --no-dev
python cli.py start
# Or: ./start-clark.sh
```

### 4. Verify

```bash
curl http://localhost:8124/api/health
# → {"status":"ok","service":"clark","version":"0.6.0"}
```

### 5. Change config (no restart needed)

```bash
# Edit clark.json, then:
curl -X POST http://localhost:8124/api/reload
# → {"status":"ok","message":"Configuration reloaded"}
```

---

## API Reference

### Health

| Method | Route | Description |
|--------|-------|-------------|
| `GET` | `/api/health` | Basic health check |
| `GET` | `/api/health/detailed` | Module-level health |
| `GET` | `/api/modules` | List registered modules |

### Reminders

| Method | Route | Description |
|--------|-------|-------------|
| `POST` | `/api/reminders` | Create a reminder |
| `GET` | `/api/reminders` | List reminders (filter: `fired=true/false`) |
| `GET` | `/api/reminders/:id` | Get reminder details |
| `DELETE` | `/api/reminders/:id` | Cancel/delete a reminder |
| `POST` | `/api/reminders/:id/done` | Mark as done |

```bash
curl -X POST http://localhost:8124/api/reminders \
  -H "Content-Type: application/json" \
  -d '{"text": "Team standup", "time": "2026-06-02T09:00:00+07:00", "alert_before_minutes": 10}'
```

### Agenda

| Method | Route | Description |
|--------|-------|-------------|
| `GET` | `/api/agenda` | Query agenda (`?range=today` / `?range=tomorrow` / `?range=week` / `?date=YYYY-MM-DD`) |
| `POST` | `/api/agenda/:id/done` | Mark agenda item done |
| `POST` | `/api/agenda/done-all` | Mark all today's items done |

### Notes

| Method | Route | Description |
|--------|-------|-------------|
| `POST` | `/api/notes` | Save a note |
| `GET` | `/api/notes` | List notes |
| `GET` | `/api/notes/search?q=...` | Full-text search notes |
| `GET` | `/api/notes/:id` | Get note |
| `PUT` | `/api/notes/:id` | Update note |
| `DELETE` | `/api/notes/:id` | Delete note |

### Email Automation

| Method | Route | Description |
|--------|-------|-------------|
| `GET` | `/api/email/status` | Provider status + DB stats + scan history |
| `POST` | `/api/email/scan` | Trigger scan — dedup, classify, notify |
| `GET` | `/api/email/search?q=...` | Instant local search (no API call) |
| `POST` | `/api/email/notified` | Mark scanned emails as notified |
| `POST` | `/api/email/cleanup` | Delete drafts / archive old (opt-in write mode) |

```bash
# Scan
curl -X POST http://localhost:8124/api/email/scan

# Search (local DB, instant)
curl http://localhost:8124/api/email/search?q=jago

# Status with stats
curl http://localhost:8124/api/email/status
```

Features:
- **Provider-agnostic**: Gmail + extensible to IMAP/Outlook
- **Privacy-first**: metadata only (from, subject, date, snippet) — never body content
- **Email tracking DB**: `~/.clark/email.db` — dedup against previous scans
- **Smart notifications**: only new (first-seen) items surfaced; older unread in separate section
- **Priority ordering**: security > billing > account > followup > archive
- **Local search**: query tracked emails instantly without API calls
- **Scan audit**: every scan logged with counts, duration, errors
- **Improved classifier**: trained on real inbox data (50 sample), Indonesian keyword support

### Scheduler (Cron Jobs)

| Method | Route | Description |
|--------|-------|-------------|
| `POST` | `/api/scheduler/jobs` | Create a scheduled job |
| `GET` | `/api/scheduler/jobs` | List all jobs |
| `GET` | `/api/scheduler/jobs/:id` | Get job details |
| `PUT` | `/api/scheduler/jobs/:id` | Update job config |
| `DELETE` | `/api/scheduler/jobs/:id` | Delete job |
| `POST` | `/api/scheduler/jobs/:id/trigger` | Trigger immediately |
| `POST` | `/api/scheduler/jobs/:id/pause` | Pause job |
| `POST` | `/api/scheduler/jobs/:id/resume` | Resume job |
| `GET` | `/api/scheduler/jobs/:id/runs` | Execution history |
| `GET` | `/api/scheduler/stats` | Aggregate stats |
| `GET` | `/api/scheduler/handlers` | Available job types |

### Job Types

| Type | Description | Payload |
|------|-------------|---------|
| `send_message` | Send arbitrary Telegram message | `{"chat_id": 123456789, "text": "...", "parse_mode": "HTML"}` |
| `send_agenda` | Send daily agenda summary | `{"chat_id": 123456789, "range": "today"}` / `"tomorrow"` |
| `reminder_alert` | Fire a reminder notification | `{"reminder_id": 42}` |

### Schedule Types

| Type | Config Example | Behavior |
|------|---------------|----------|
| `cron` | `{"cron": "0 6 * * *", "tz": "Asia/Jakarta"}` | Standard cron expression in given timezone |
| `interval` | `{"interval_minutes": 30}` | Every N minutes |
| `once` | `{"at": "2026-06-02T09:00:00+07:00"}` | One-shot, auto-disables after firing |

---

## Scheduler Manager

The scheduler replaces a naive polling loop with a precise async tick system:

```
Old:  while True → poll DB → sleep 300s  (±5 min precision)
New:  compute next run → sleep precisely → execute due jobs  (sub-second precision)
```

Key features:
- **Cron expressions** via `croniter` (crontab syntax, timezone-aware)
- **Retry** on failure (configurable per job)
- **Run history** — every execution logged with status/error/result
- **Auto-disable** once-type jobs after first fire
- **Manual trigger** — test any job immediately via API

---

## Configuration: `clark.json`

All config lives in a single JSON file. No `.env`.

```json
{
  "telegram": {
    "token": "789012:ABC...",
    "default_chat_id": 123456789
  },
  "database": {
    "path": "data/assistant.db"
  },
  "modules": {
    "reminders": { "enabled": true },
    "notes": { "enabled": true },
    "agenda": { "enabled": true },
    "scheduler": { "enabled": true },
    "uptime": { "enabled": true },
    "email_automation": {
      "enabled": false,
      "provider": "gmail",
      "credentials_path": "~/.config/email/credentials.json",
      "token_path": "~/.config/email/token.json",
      "db_path": "~/.clark/email.db",
      "scan_schedule": "0 7 * * *",
      "scan_limit": 50,
      "chat_id": 123456789,
      "read_only": true
    }
  }
}
```

Apply config changes:

```bash
curl -X POST http://localhost:8124/api/reload
```

---

## Deploy

### 1. Generate Service File

The systemd unit is generated from a template + `clark.json` — no manual path editing needed.

```bash
python cli.py deploy service
# → ✅ deploy/clark.service generated
#    Paths, user, and resources read from clark.json + auto-detection
```

To override defaults, add an optional `deploy` section to `clark.json`:

```json
{
  "deploy": {
    "host": "127.0.0.1",
    "port": 8124,
    "workers": 1,
    "memory_max": "256M",
    "cpu_quota": "50%"
  }
}
```

### 2. Install Service

```bash
sudo cp deploy/clark.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now clark
```

### Manual

```bash
python cli.py start   # start as background process
python cli.py stop    # graceful stop
python cli.py status  # health check
```

---

## Agent Integration

See [docs/agent-integration.md](docs/agent-integration.md) for the complete guide on how agentic AI systems consume this API.

---

## Changelog

### v0.6.0 — Renamed to clark
- Project renamed from `ai-assistant-light` → `clark`
- Strip LLM layer, bot baggage, unused scripts/config
- New SchedulerManager with cron/interval/once support
- 11 new scheduler API endpoints
- New job types: `send_message`, `send_agenda`, `reminder_alert`
- Agent integration guide

### v0.5.0 — REST API + Plugin system
(see [CHANGELOG.md](CHANGELOG.md) for earlier versions)
