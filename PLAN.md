# Clark — The AI's Desk Clerk

> **Tagline:** *Ask clark.*
> **Version:** v0.6.0 → v0.7.0
> **Identity:** API backend that handles menial tasks so AI agents can focus on what matters.

```
┌──────────────────────────────┐
│                              │
│           CLARK              │
│    clerk at your desk        │
│                              │
│   POST /api/reminders        │
│   POST /api/notes            │
│   GET  /api/agenda           │
│   POST /api/scheduler/jobs   │
│   POST /api/reload           │
│                              │
└──────────────────────────────┘
```

---

## What Is Clark?

Clark is a REST API backend that AI agents (like Sangkuni) talk to.

```
Sangkuni: "Let me ask clark to create a reminder."
          → POST /api/reminders { text: "Meeting 10:00", time: "10:00" }

Sangkuni: "I'll ask clark what's on your agenda."
          → GET /api/agenda?range=today

Sangkuni: "Let me clark that note."
          → POST /api/notes { text: "Meeting notes from standup"

Sangkuni: "Enable weather for Jakarta at 06:00."
          → Edit clark.json → POST /api/reload
```

Clark does **no AI reasoning**. That's OpenClaw's job. Clark just handles:
- ✅ Reminders (CRUD)
- ✅ Notes (CRUD + search)
- ✅ Agenda (query + format)
- ✅ Scheduler (cron/interval/once jobs)
- ✅ Telegram notifications
- ✅ Hot reload config

---

## Philosophy

See [docs/coding-philosophy.md](docs/coding-philosophy.md) for full details.

**In short:**
- **Declarative** — modules declare what they are, framework wires them
- **Visible config** — `clark.json` is the one source of truth
- **Three files, one folder** — new feature = 3 files in `modules/`, zero core edits
- **Hot reload** — `POST /api/reload` enables/disables modules without restart
- **No .env** — all configuration in `clark.json`
- **No AI** — clark handles infrastructure, not reasoning

---

## Current State (v0.6.0)

### Working

| Feature | Endpoints | What's configurable |
|---------|-----------|-------------------|
| Reminders CRUD | `POST/GET/PUT/DELETE /api/reminders` | Enabled/disabled |
| Notes CRUD + search | `POST/GET/PUT/DELETE /api/notes; GET /api/notes/search` | Enabled/disabled |
| Agenda queries | `GET /api/agenda?range=today\|tomorrow\|week\|range=DATE-DATE` | Enabled/disabled |
| Scheduler manager | 11 endpoints for jobs CRUD, trigger, pause, resume, runs, stats | Enabled/disabled |
| Telegram notifier | Sends messages via Bot API | Token + default chat ID |
| Module system | Base class + discovery + lifecycle | Module enable/disable |
| Daily agenda jobs | #5 06:00 (today), #6 16:00 (tomorrow) | Schedule time, range |
| Hot reload | `POST /api/reload` | — |
| Health check | `GET /api/health`, `GET /api/health/detailed` | — |

### Running On

- **Host:** Raspberry Pi (Linux arm64)
- **Port:** `localhost:8124`
- **DB:** SQLite (aiosqlite)
- **Config:** `clark.json`
- **Python:** 3.11+

---

## Roadmap

### ✓ v0.6.0 — Foundation
- [x] Strip LLM layer
- [x] Build scheduler engine
- [x] Create daily agenda jobs
- [x] Rename project to clark
- [x] Extract `core/` package

### 🔲 v0.7.0 — Declarative Module System

Phase 2 — Convert built-in features to `modules/`:

```
Phase 2a: Convert reminders → modules/reminders/
Phase 2b: Convert notes → modules/notes/
Phase 2c: Convert agenda → modules/agenda/
Phase 2d: Convert scheduler API → modules/scheduler/
Phase 2e: Wire hot reload (POST /api/reload)
Phase 2f: Add clark.json with module config
Phase 2g: Remove .env — all config to clark.json
```

**After Phase 2:** Core is stable. New features are folders in `modules/`.

### ✅ Phase 3 — Scaffolding CLI + API

One command creates a complete module skeleton:

```bash
# CLI (for humans)
python cli.py make module --name weather --desc "Daily forecast" --with-handler

# API (for agents)
curl -X POST /api/modules/scaffold \
  -H "Content-Type: application/json" \
  -d '{"name": "weather", "with_handler": true}'
```

**What happens:**
- Creates `modules/weather/__init__.py`, `routes.py`, optional `handler.py`
- Adds `"weather": {"enabled": false}` to `clark.json`
- Prints next steps: edit files → enable → `POST /api/reload`

**Zero dependencies.** `cli.py` uses only `argparse` (stdlib).
Templates in `core/templates.py` — shared between CLI and API.

### ✅ Phase 3.5 — Start/Stop/Status Scripts + CLI

Proof-of-concept management scripts at project root — no server needed:

```bash
./start-clark.sh      # daemonize uvicorn, write PID
./stop-clark.sh       # graceful shutdown via PID file
./status-clark.sh     # check PID + curl /api/health
```

**Or via CLI** (same logic):

```bash
python cli.py start
python cli.py stop
python cli.py status
```

Also includes:
- Cleanup: removed dead `scripts/start-assistant.sh`, `scripts/stop-assistant.sh`
- Fixed `deploy/clark.service` paths and removed `.env` reference

### 🔲 Future Modules (Example Ideas)

```bash
# Scaffold any of these with:
python cli.py make module --name <name> --with-handler
```

| Module | What it does | Config |
|--------|-------------|--------|
| `weather` | Daily weather forecast at 06:00 | City, unit |
| `email` | Check IMAP, notify on important mail | IMAP host, credentials |
| `rss` | Monitor feeds, alert on new items | Feed URLs |

---

## Configuration: `clark.json`

Single JSON file, readable by humans and agents.

```json
{
  "telegram": {
    "token": "789012:ABC...",
    "default_chat_id": 123456789
  },
  "database": {
    "path": "data/clark.db"
  },
  "modules": {
    "reminders": { "enabled": true },
    "notes": { "enabled": true },
    "agenda": { "enabled": true },
    "scheduler": { "enabled": true }
  }
}
```

See [docs/coding-philosophy.md](docs/coding-philosophy.md) for module config merging rules.

---

## Project Structure (Target)

```
clark/
├── core/                       ← framework (~500 lines)
│   ├── app.py                  ← create_app() factory
│   ├── config.py               ← ClarkConfig from clark.json
│   ├── database.py             ← DB + migrations
│   ├── notifier.py             ← Telegram sender
│   ├── module.py               ← Module base class
│   ├── module_manager.py       ← Discovery + lifecycle
│   └── scheduler/
│       ├── __init__.py          ← SchedulerManager
│       ├── job_store.py         ← DB access
│       └── handlers.py          ← send_message, send_agenda, reminder_alert
│
├── modules/                    ← desk drawers
│   ├── reminders/
│   │   ├── __init__.py
│   │   └── routes.py
│   ├── notes/
│   │   ├── __init__.py
│   │   └── routes.py
│   ├── agenda/
│   │   ├── __init__.py
│   │   └── routes.py
│   └── scheduler/
│       ├── __init__.py
│       └── routes.py
│
├── clark.json                  ← one source of truth
├── app.py                      ← 3 lines
├── migrations/                 ← core migrations
├── data/                       ← SQLite
├── docs/
│   ├── coding-philosophy.md    ← this file
│   └── agent-integration.md    ← agent guide
├── scripts/
├── deploy/
├── tests/
└── pyproject.toml
```

---

## Quick Start

```bash
git clone https://github.com/permadihendra/clark-assistant
cd clark-assistant
uv sync --no-dev

# Edit config
cp clark.json.example clark.json
# Fill in telegram.token

# Run
uv run uvicorn app:app --host 127.0.0.1 --port 8124

# Verify
curl http://localhost:8124/api/health
# → {"status":"ok","service":"clark","version":"0.6.0"}
```

## Scaffold a Module

```bash
# CLI — no server needed
python cli.py make module --name weather --desc "Daily forecast" --with-handler

# Or via API — server must be running
curl -X POST http://localhost:8124/api/modules/scaffold \
  -H "Content-Type: application/json" \
  -d '{"name": "weather"}'
```

Then enable it and reload:

```bash
# Edit clark.json → set "weather": {"enabled": true}
curl -X POST http://localhost:8124/api/reload
```

---

## Deploy

### Generate Service File

```bash
python cli.py deploy service
# → ✅ deploy/clark.service generated from template + clark.json
```

### Install

```bash
sudo cp deploy/clark.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now clark
```
