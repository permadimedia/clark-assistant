# Coding Philosophy — Clark

> *Declarative. Visible. Minimal. Hot-reloadable.*

---

## Core Principles

### 1. Declarative over Imperative

A module **declares what it is** — the framework wires it.

```python
# ✅ Declarative — module says what it provides
class WeatherModule(Module):
    name = "weather"
    routes = "modules.weather.routes"          # framework auto-discovers
    job_handlers = {"forecast": "..."}          # framework auto-registers
    config_defaults = {"enabled": False}        # framework auto-merges

# ❌ Imperative — developer must wire everything
app.include_router(weather_router)
registry.register("weather_forecast", handler)
```

**Why:** Declarative makes both humans and agents productive. Anyone can add a new module by copying a folder and changing 3 values. No need to understand the framework's internals.

---

### 2. Three Files, One Folder

A new feature = **3 files in `modules/<name>/`**. Zero changes outside.

```
modules/weather/
├── __init__.py          ← Declaration (name, routes, handlers, defaults)
├── routes.py            ← API endpoints (if any)
├── handler.py           ← Job handlers (if needed)
└── migrations/          ← SQL files (if new tables needed)
```

**No:** editing `app/main.py`, `core/module_manager.py`, or any other core file.

**Exception:** If your feature needs a new database table, the migration file lives in your module's folder. The framework discovers and runs it.

---

### 3. Config is Visible

`clark.json` is the one source of truth. Every tweakable value lives there.

```json
{
  "telegram": { "token": "...", "default_chat_id": 123456789 },
  "modules": {
    "weather": { "enabled": false, "city": "Jakarta" }
  }
}
```

**No:** `.env` files scattered around, `os.environ.get("WEATHER_API_KEY")` that only exists in a README note.

**Yes:** Everything in one JSON, readable by both humans and agents. Sangkuni can read `clark.json`, edit a value, and clark picks it up on the next hot reload.

**Hot reload rule:** `POST /api/reload` reloads `clark.json` and reconfigures modules. Running modules are not interrupted — only their config changes.

---

### 4. Module Config Merging

```
Module provides:  config_defaults = {"enabled": false, "city": "Jakarta"}
clark.json:       "weather": {"city": "Surabaya"}

Result:           {"enabled": false, "city": "Surabaya"}
```

The central `clark.json` only needs to specify **overrides**. Defaults come from the module's declaration. This keeps `clark.json` small while making every module configurable out of the box.

---

### 5. Modules Are Self-Contained

A module folder ships with everything it needs:

- **Its own routes** — no central router file
- **Its own migrations** — no central migration list
- **Its own handlers** — no central HANDLER_MAP
- **Its own defaults** — no config scattered elsewhere

```python
# modules/weather/__init__.py
from core.module import Module

class WeatherModule(Module):
    name = "weather"
    description = "Daily weather forecast notifications"
    version = "0.1.0"
    dependencies = ["core.notifier"]           # what it needs from core

    routes = "modules.weather.routes"           # dot-path to routes file
                                               # framework calls app.include_router()
    job_handlers = {
        "weather_forecast": "modules.weather.handler:handle_forecast",
    }
    config_defaults = {
        "enabled": False,
        "city": "Jakarta",
        "unit": "celsius",
        "send_at": "06:00",
    }
```

---

### 6. No AI, No LLM

Clark does not reason. Clark does not think. Clark handles the boring infrastructure:

- ✅ CRUD operations
- ✅ Scheduled execution
- ✅ Telegram notifications
- ✅ Data persistence

**AI reasoning belongs to OpenClaw (Sangkuni).** Clark is the tool the AI picks up — not the brain.

This means:
- No AI provider keys in clark.json
- No prompt templates
- No LLM dependencies in pyproject.toml
- Every endpoint is predictable, stateless, and self-documenting

---

### 7. Async-Native

Every operation is async. No blocking calls.

```python
async def get_db() -> aiosqlite.Connection:
    """Always await. Never block."""
```

This keeps the server responsive even under load. Multiple jobs can run concurrently without blocking each other.

---

### 8. Minimal Core, Rich Modules

The `core/` package is deliberately small (~500 lines total).

```
core/
├── config.py              ← 50 lines (ClarkConfig)
├── database.py            ← 80 lines (DB + migrations)
├── notifier.py            ← 60 lines (Telegram sender)
├── module.py              ← 30 lines (Module base class)
├── module_manager.py      ← 100 lines (discovery + lifecycle)
├── scheduler/             ← 200 lines (engine + job store + handlers)
└── app.py                 ← 80 lines (create_app factory)
```

Everything else lives in `modules/`. Core is the foundation. Modules are the house.

---

### 9. The Agent's View

When Sangkuni wants to add a feature:

```
Sangkuni: "Add weather forecast at 06:00"
   1. Create modules/weather/ with __init__.py + routes.py (+ handler.py)
   2. Edit clark.json: modules.weather.enabled = true
   3. POST /api/reload
   4. Done. Weather forecast fires daily at 06:00.
```

No reading the framework source. No wondering "where do I register this?".
Just: create folder → edit JSON → reload.

---

## Directory Structure Target

### Generated Artifacts

Anything that can be generated from `clark.json` + a template is **not committed** — it's built at deploy time. This keeps secrets out of git and paths reproducible.

```
clark.json.example          ──→  clark.json              (user copies, fills in)
deploy/service.template     ──→  deploy/clark.service    (cli.py deploy service)
```

```
clark/                          ← project root
├── core/                       ← framework (stable, ~500 lines)
│   ├── __init__.py
│   ├── app.py                  ← create_app() factory
│   ├── config.py               ← ClarkConfig from clark.json
│   ├── database.py             ← DB + migration runner
│   ├── notifier.py             ← Telegram sender
│   ├── module.py               ← Module base class
│   ├── module_manager.py       ← Discovery + lifecycle
│   └── scheduler/
│       ├── __init__.py          ← SchedulerManager
│       ├── job_store.py         ← DB access
│       └── handlers.py          ← Built-in handlers
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
│   └── scheduler/              ← scheduler management API
│       ├── __init__.py
│       └── routes.py
│
├── clark.json                  ← one source of truth
├── app.py                      ← 3 lines: from core.app import create_app; app = create_app()
├── migrations/                 ← core migrations only
├── data/                       ← SQLite lives here
├── docs/                       ← documentation
├── scripts/
├── deploy/
├── tests/
└── pyproject.toml
```

---

## Example: Adding Weather Module

### Step 1: Create folder

```bash
mkdir -p modules/weather/migrations
```

### Step 2: Write declaration

```python
# modules/weather/__init__.py
from core.module import Module

class WeatherModule(Module):
    name = "weather"
    description = "Daily weather forecast via Telegram"
    version = "0.1.0"
    routes = "modules.weather.routes"
    job_handlers = {
        "weather_forecast": "modules.weather.handler:handle_forecast",
    }
    config_defaults = {
        "enabled": False,
        "city": "Jakarta",
        "unit": "celsius",
    }
```

### Step 3: Write routes (API endpoints)

```python
# modules/weather/routes.py
from fastapi import APIRouter

router = APIRouter(prefix="/api/weather", tags=["weather"])

@router.get("/forecast")
async def get_forecast():
    """Get current weather."""
    return {"city": "Jakarta", "temp": 32, "condition": "partly cloudy"}
```

### Step 4: Write handler (for scheduled jobs)

```python
# modules/weather/handler.py
from core.notifier import send_message

async def handle_forecast(job):
    """Fetch weather and send to Telegram."""
    city = job.payload.get("city", "Jakarta")
    text = f"🌤️ Weather in {city}: 32°C, partly cloudy"
    ok = await send_message(text, chat_id=job.payload["chat_id"])
    return f"Weather sent for {city}"
```

### Step 5: Edit clark.json

```json
{
  "modules": {
    "weather": {
      "enabled": true,
      "city": "Jakarta"
    }
  }
}
```

### Step 6: Hot reload

```bash
curl -X POST http://localhost:8124/api/reload
```

---

## What NOT To Do

- ❌ Don't edit `core/` files to add a feature. Create a module.
- ❌ Don't add `.env` variables for module config. Use `clark.json`.
- ❌ Don't add AI/LLM dependencies. Clark is not a reasoning engine.
- ❌ Don't import directly from other modules. Use `core` services only.
- ❌ Don't create global state in modules. Use the database.
