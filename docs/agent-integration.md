# Agent Integration Guide

> How agentic AI systems (OpenClaw, Claude, etc.) consume `clark`.

---

## Architecture

```
┌─────────────────────┐       HTTP/JSON        ┌──────────────────────────────┐
│  OpenClaw Agent     │  ────────────────────►  │  clark                      │
│  (Sangkuni 🦊)      │  ◀────────────────────  │  localhost:8124  — Ask clark. │
│                     │      responses          │                              │
│  - Reasoning        │                         │  ┌─ Reminders ─────────────┐ │
│  - Decision-making  │                         │  │ POST /api/reminders     │ │
│  - Scheduling       │                         │  │ GET  /api/agenda        │ │
│  - Memory           │                         │  ├─ Scheduler ────────────┤ │
│                     │                         │  │ POST /api/scheduler/*  │ │
│  Runs on:           │                         │  │ GET  /api/scheduler/*  │ │
│  - Raspberry Pi     │                         │  ├─ Notes ───────────────┤ │
│  - Any Linux host   │                         │  │ POST/GET/PUT/DEL notes │ │
│                     │                         │  └─ Notifier ────────────┘ │
└─────────────────────┘                         └──────────────────────────────┘
                                                        │
                                                   Telegram Bot API
                                                        │
                                                   ┌────▼────┐
                                                   │  Your   │
                                                   │ Telegram│
                                                   └─────────┘
```

**Key principle:** The agent calls the API. The API never calls the agent. This keeps the agent stateless and the API reliable.

---

## Agent Boot Cycle: Keep clark Alive

clark is your right hand — it must be running before you use any of its APIs.

On **every agent wakeup** (session start, heartbeat, or restart):

```bash
# Step 1: Check if clark is alive
./status-clark.sh

# Step 2: Start if dead
./start-clark.sh

# Step 3: Verify healthy before calling APIs
curl -sf http://localhost:8124/api/health
# → {"status":"ok","service":"clark","version":"0.7.0"}
```

Or via CLI (same thing):

```bash
python cli.py status   # check
python cli.py start    # start if down
```

**You can embed this in your own startup routine.** For example, in OpenClaw:

```
On every session start / heartbeat:
  1. Check if clark is running → python cli.py status
  2. If not running → python cli.py start
  3. Wait for healthy → curl -sf /api/health
  4. Proceed with agent workflow
```

> **Why?** clark runs as a background process, not a system daemon. It doesn't auto-start on boot.
> The agent is the supervisor. Every time you wake up, check your tools — clark is one of them.

### Past-Due Recovery

If clark was down when a reminder was supposed to fire, don't worry —
the **catch-up** mechanism on startup scans for missed reminders and fires them immediately:

```
2026-06-01 10:59:26 [INFO] core.scheduler: Catch-up: recovered reminder #10 (due 09:00)
2026-06-01 10:59:26 [INFO] core.scheduler: Catch-up: recovered reminder #11 (due 10:52)
2026-06-01 10:59:26 [INFO] core.scheduler: Catch-up done: 2 recovered, 0 failed
```

No reminder is ever lost — even if clark was offline during the scheduled time.

---

## Presentation Guidelines (for Agents)

When presenting clark data to users, format matters. These rules ensure
readability on **Telegram**, **WhatsApp**, and other chat platforms.

### No Markdown Tables

Tables render poorly on mobile Telegram and WhatsApp. Use bullet lists instead.

```diff
- BAD (table — unreadable on mobile):
  | ⏰ | Acara | Peserta |
  |----|-------|---------|
  | 09:00 | Team Standup | Engineering |
  | 14:00 | Client Demo | Product, Sales |

+ GOOD (bullet list — readable everywhere):
+ ⏰ 09.00 — Team Standup
+ 👥 Engineering
+ 🖇️ Notifikasi jam 08.50
+
+ ⏰ 14.00 — Client Demo
+ 👥 Product, Sales
+ 🖇️ Notifikasi jam 13.50
```

### Platform-Specific

- **Telegram** — No tables. Bullet lists only. Keep lines short.
- **WhatsApp** — No tables, no headers. Use **bold** or CAPS for emphasis.
- **Discord** — No tables. Wrap multiple links in `<>` to suppress embeds.

### Reading Time

Agenda/reminder outputs should be scannable in 3 seconds.
Group by time, use emoji markers, and **never dump raw JSON** to the user.

## Configuration: `clark.json`

All config lives in a single `clark.json` file. No `.env`. One file, readable by humans and agents.

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
    "weather": {
      "enabled": false,
      "city": "Jakarta"
    }
  }
}
```

> **⚠️ Config vs Scheduled Jobs**
> `clark.json` is for **runtime settings** only (token, module toggles, DB path).
> It does **not** auto-create scheduled jobs. To set up recurring agenda
> delivery, agents must create cron jobs via `POST /api/scheduler/jobs`.
> See [Scheduler Patterns](#scheduler-patterns) below.

### Agent Workflow for Config Changes

```
Sangkuni: "Enable weather for Jakarta."
  1. Read clark.json → find modules.weather.enabled = false
  2. Edit clark.json → set enabled = true, city = "Jakarta"
  3. POST /api/reload
  4. Weather module now active
```

### Hot Reload

```bash
curl -X POST http://localhost:8124/api/reload
# → {"status":"ok","message":"Configuration reloaded","plugins_reloaded":["weather"]}
```

Hot reload:
- Reads `clark.json` fresh
- Enables newly enabled modules
- Disables newly disabled modules
- Updates module configs without restart
- **Running jobs are not interrupted**

---

## Core Workflows

### 1. Create a Reminder

The agent creates a one-shot reminder. The API fires it **before** the event (default 10 min) so you have time to act.

```bash
# Agent calls:
curl -X POST http://localhost:8124/api/reminders \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Review sprint progress with team",
    "time": "2026-06-02T14:00:00+07:00",
    "alert_before_minutes": 10
  }'
```

**What happens:**
1. API stores the reminder in SQLite (event time: 14:00)
2. Auto-creates a scheduler job that fires at **13:50** (10 min before)
3. At 13:50, Telegram receives: `🔔 REMINDER — Review sprint progress with team ⏰ 14:00`
4. The notification shows the actual event time, so you know how much time remains

**Configure lead time:**
- `alert_before_minutes: 10` → notified 10 min before event (default)
- `alert_before_minutes: 0` → notified exactly at event time (legacy)
- `alert_before_minutes: 30` → notified half an hour before

**Notification format:**
```
🔔 📋 Sprint Review              ← first line bold (title)
👥 Product, Engineering, Design  ← details normal weight
🏢 Meeting Room B
🖇️ https://meet.google.com/abc-defg-hij
📌 1. Demo completed features

⏰ 14:00
━━━━━━━━━━━━━━━━
🦊 clark                          ← footer, not ai-assistant-light
```
Only the first line is bolded. Details, participants, location, and agenda items display as normal text. Footer says `clark`.

### 2. Query Today's Agenda

The agent checks what's scheduled today:

```bash
curl -s http://localhost:8124/api/agenda?range=today
```

Response:
```json
{
  "date": "2026-06-01",
  "items": [
    {"id": 10, "text": "Team standup", "time": "09:00", "done": false},
    {"id": 11, "text": "Client meeting", "time": "14:00", "done": false}
  ],
  "total": 2,
  "done_count": 0
}
```

The agent can then decide what to tell you, or mark items done:

```bash
curl -s -X POST http://localhost:8124/api/agenda/10/done
```

### 3. Schedule Recurring Agenda Delivery

The agent sets up a cron job once — the API handles it forever.

**06:00 WIB — Send today's agenda:**

```bash
curl -X POST http://localhost:8124/api/scheduler/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Agenda Pagi 06:00",
    "job_type": "send_agenda",
    "schedule_type": "cron",
    "schedule_config": {"cron": "0 6 * * *", "tz": "Asia/Jakarta"},
    "payload": {"chat_id": 123456789, "range": "today"}
  }'
```

**16:00 WIB — Send tomorrow's agenda:**

```bash
curl -X POST http://localhost:8124/api/scheduler/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Agenda Sore 16:00",
    "job_type": "send_agenda",
    "schedule_type": "cron",
    "schedule_config": {"cron": "0 16 * * *", "tz": "Asia/Jakarta"},
    "payload": {"chat_id": 123456789, "range": "tomorrow"}
  }'
```

**After setup:** Both jobs run indefinitely. The agent doesn't need to check again — the API handles execution.

### 4. Send an Immediate Notification

```bash
curl -X POST http://localhost:8124/api/scheduler/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Quick notification",
    "job_type": "send_message",
    "schedule_type": "once",
    "schedule_config": {"at": "2026-06-01T09:30:00+07:00"},
    "payload": {"chat_id": 123456789, "text": "⏰ <b>Meeting in 5 minutes!</b>"}
  }'
```

Or fire immediately via trigger:

```bash
curl -s -X POST http://localhost:8124/api/scheduler/jobs/42/trigger
```

### 5. Save and Search Notes

The agent can save reference information and retrieve it later:

```bash
# Save
curl -X POST http://localhost:8124/api/notes \
  -H "Content-Type: application/json" \
  -d '{"text": "Remember to review pull request before Friday"}'

# Search
curl -s "http://localhost:8124/api/notes/search?q=server+ip"
```

---

## Scheduler Patterns

### Pattern A: Agent Sets Up → API Runs Forever

Best for repetitive tasks. The agent calculates _what_ should happen, the API handles _when_ it happens.

```
Agent creates cron job ──► API stores it ──► API fires every X hours/days ──► Telegram
(one-time call)            (persistent)       (zero agent involvement)
```

Example: Daily agenda at 06:00 and 16:00.

### Pattern B: Agent Triggers on Demand

Agent decides → calls trigger → message sent immediately.

```
Agent detects event ──► POST /api/reminders ──► API fires at scheduled time
```

Example: "Remind me in 30 minutes about the call."

### Pattern C: Hybrid

Agent sets up a recurring job with a handler that calls the agent's decision logic (future pattern — requires adding a `webhook` job type).

```
Job fires ──► API calls agent webhook ──► agent decides action ──► result back to API
```

---

## Job Lifecycle

```
POST /api/scheduler/jobs
        │
   ┌────▼────┐
   │  Pending │  (enabled=true, waiting for next_run_at)
   └────┬────┘
        │
   ┌────▼────┐
   │ Running │  (handler executing)
   └────┬────┘
        │
   ┌────▼──────┐     ┌────────┐
   │  Success   │  or │ Failed │  (retries if max_retries > 0)
   └────┬──────┘     └────┬───┘
        │                 │
   ┌────▼────┐       ┌────▼───────┐
   │  Next   │       │  Exhausted  │  (disabled, logged)
   │  run    │       │  or Once    │
   └─────────┘       └────────────┘
```

---

## Error Handling

### Telegram Down

If the notifier fails to send (network error, rate limit):
- The job is marked `failed` in the run history
- If `max_retries > 0`, it retries after `retry_delay_s`
- After exhausting retries, the job stays enabled (next run still fires)

### API Restart

All data is in SQLite — nothing lost on restart. The SchedulerManager re-reads all enabled jobs and continues from their `next_run_at` timestamps.

### Cron Job Overruns

If a job takes longer than the interval between runs, it simply runs again when the next tick happens. No queue buildup.

---

## Security

- API binds to **127.0.0.1:8124** — localhost only, not exposed to network
- No authentication tokens needed (localhost trust model)
- Telegram API key stored in `clark.json` (chmod 600)
- SQLite database in `data/` directory
- Scripts runner removed from codebase (no remote code execution)

---

## Module Management: Adding Features

New features are added by creating a folder in `modules/`. See [coding-philosophy.md](coding-philosophy.md) for the full guide.

**Quick recipe for agents:**

```
1. Create modules/<name>/__init__.py  → Module declaration
2. Create modules/<name>/routes.py    → API endpoints (if needed)
3. Edit clark.json → enable the module
4. POST /api/reload
```

The framework auto-discovers the module, registers its routes, and merges its config. Zero core edits.

---

## Agent Discovery: OpenClaw Skill

For agents running in **OpenClaw**, a skill at `~/.openclaw/plugin-skills/clark/SKILL.md`
is auto-discovered when the agent needs reminders, notes, agenda, or scheduling.

The skill contains:

| What | Why |
|------|-----|
| **Startup sequence** | Check → start → verify healthy on every wakeup |
| **Max 3 exec rule** | Clarify first, execute in ≤3 calls. No silent chains. |
| **API reference** | Key endpoints, job types, schedule types |
| **Behavior rules** | Ask clarifying questions before assuming defaults |

A fresh agent that clones the repo and runs on OpenClaw will automatically
load this skill when a matching task appears — no manual setup needed.

### Install via CLI

```bash
cd clark-assistant
python cli.py install-skill agent --openclaw
# → ✅ clark skill installed for OpenClaw
# → New session → skill auto-discovered
```

**What it does:** Uses OpenClaw's native `openclaw skills install ./path --as clark`
to copy the skill from the repo into the workspace skills root:
```
openclaw skills install ./openclaw/skills/clark --as clark
```

This is the **recommended** method — OpenClaw tracks the install, handles
copying correctly, and respects security rules.

The skill lives **in the repo** (`openclaw/skills/clark/SKILL.md`)
so it's version-controlled. After a repo update, re-run the command to
refresh.

**Description** (auto-match triggers in OpenClaw):
> Use clark REST API (localhost:8124) for reminders, agenda, notes,
> and scheduling tasks.

When OpenClaw sees a task matching this description, it loads the skill.
The skill contains startup sequence, behavioral rules (max 3 exec,
clarify first, Telegram-friendly formatting), and a full API reference.

### Uninstall

```bash
cd clark-assistant
python cli.py uninstall-skill agent --openclaw
# → ✅ clark skill uninstalled from OpenClaw
# → Effect on next session
```

### Platform Extensibility

The command is designed to support multiple agent platforms:

```bash
python cli.py install-skill agent --openclaw   # today
python cli.py install-skill agent --codex      # future
python cli.py install-skill agent --claude     # future
```

Each platform gets its own install mechanism under the hood.

### How It Works

```
repo/openclaw/skills/clark/SKILL.md   ← canonical (version-controlled)
       │
       │ python cli.py install-skill agent --openclaw
       │   └── openclaw skills install ./path --as clark
       ▼
~/.openclaw/workspace/skills/clark/   ← auto-discovered by OpenClaw
       │
       │ loaded into next session
       ▼
   Agent gets behavioral rules + API reference
```

This pattern makes the skill **part of the project**, not a manual setup step.
Fresh clone → `python cli.py install-skill agent --openclaw` → agent
knows how to use clark.

### Skill Discovery (How Agents Learn)

OpenClaw scans these skill roots **at session start**:

- **Highest:** `<workspace>/skills/` (per-agent)
- `<workspace>/.agents/skills/`
- `~/.agents/skills/`
- `~/.openclaw/skills/`
- **Lowest:** Bundled (shipped with OpenClaw)

The `description` field in `SKILL.md` frontmatter is shown to the agent
in its system prompt. When a task matches, the agent reads the skill
file and follows its instructions.

```markdown
---
name: clark
description: Use clark REST API (localhost:8124) for reminders, agenda, notes, and scheduling tasks.
---
```

No symlink workarounds needed — the native `openclaw skills install`
command handles copying securely within the workspace root.

---

## Quick Reference (for Agent Prompt)

If you're an agent reading this, here's all you need to know:

```
INSTALL (one-time, after fresh clone):
  python cli.py install-skill agent --openclaw   ← native OpenClaw install

STARTUP (do this first thing every time you wake up):
  python cli.py status              ← is clark alive?
  python cli.py start               ← start if dead

clark running on http://localhost:8124

CONFIG:
  clark.json                         ← One file, all settings
  POST /api/reload                   ← Apply config changes

CORE ENDPOINTS:
  POST /api/reminders     → {"text": "...", "time": "ISO8601+tz",
                              "alert_before_minutes": 10}
                            ↳ notification: title bold, details normal, footer "clark"
  GET  /api/agenda        → ?range=today|tomorrow|week
  POST /api/notes         → {"text": "..."}
  GET  /api/notes/search  → ?q=keyword

SCHEDULER (cron jobs):
  POST /api/scheduler/jobs  → create recurring/one-shot job
  GET  /api/scheduler/jobs  → list all jobs
  POST /.../jobs/:id/trigger → fire immediately
  POST /.../jobs/:id/pause  → disable temporarily
  POST /.../jobs/:id/resume → re-enable

JOB TYPES:
  send_message  → {"chat_id": N, "text": "..."}
  send_agenda   → {"chat_id": N, "range": "today"|"tomorrow"}
  reminder_alert → {"reminder_id": N}

SCHEDULE TYPES:
  cron     → {"cron": "0 6 * * *", "tz": "Asia/Jakarta"}
  interval → {"interval_minutes": 30}
  once     → {"at": "2026-06-02T09:00:00+07:00"}

MODULES:
  POST /api/modules              → list active modules
  POST /api/reload               → reload clark.json

BEHAVIOR:
  "Let me clark that."         → POST /api/reminders or /api/notes
  "Ask clark about my day."    → GET /api/agenda?range=today
  "I'll ask clark to remind me." → POST /api/reminders {alert_before_minutes: 10}
                                 ↳ Telegram: first line bold, footer: 🦊 clark
  "Enable weather for Jakarta." → edit clark.json → POST /api/reload
```
