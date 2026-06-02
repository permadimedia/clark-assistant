# Clark — Framework Architecture

> **Version:** v0.7.0 | **Status:** Design
> **Goal:** Turn `clark` into a lightweight declarative framework where features = folders.

---

## The Problem

Currently, adding a feature requires editing 7 files across the codebase:

| Step | File | Change |
|------|------|--------|
| API router | `app/api/*.py` | Create new file |
| Pydantic models | `app/api/models.py` | Add schemas |
| Migration | `migrations/*.sql` | Create SQL |
| Import router | `app/main.py` | Add import |
| Job handler | `app/scheduler/handlers.py` | Add handler |
| Update HANDLER_MAP | `app/scheduler/handlers.py` | Register handler |
| Register plugin | `app/main.py` | Add to list |

**Target:** A new feature = **3 files in `modules/<name>/`**. Zero changes to `core/` or `app/main.py`.

---

## The Solution: Declarative Modules

### Module Declaration

Every module declares itself. The framework reads the declaration and wires everything.

```python
# modules/weather/__init__.py
from core.module import Module

class WeatherModule(Module):
    name = "weather"
    description = "Daily weather forecast via Telegram"
    version = "0.1.0"
    routes = "modules.weather.routes"                     # auto-register router
    job_handlers = {                                      # auto-register handlers
        "weather_forecast": "modules.weather.handler:handle_forecast",
    }
    config_defaults = {                                   # defaults merged with clark.json
        "enabled": False,
        "city": "Jakarta",
    }
```

**The framework reads this declaration and:**
1. Imports and registers `router` from the `routes` path → `app.include_router(router)`
2. Registers `job_handlers` → available via `/api/scheduler/jobs`
3. Merges `config_defaults` with `clark.json` values → module gets its config

**No core files touched. No manual registration. No import statements to add.**

---

## Target Structure

```
clark/
├── core/                           ← framework (stable)
│   ├── app.py                      ← create_app() factory
│   ├── config.py                   ← ClarkConfig from clark.json
│   ├── database.py                 ← DB + migrations
│   ├── notifier.py                 ← Telegram sender
│   ├── module.py                   ← Module base class
│   ├── module_manager.py           ← Discovery + lifecycle
│   └── scheduler/
│       ├── __init__.py              ← SchedulerManager
│       ├── job_store.py             ← DB access
│       └── handlers.py              ← Built-in handlers
│
├── modules/                        ← desk drawers
│   ├── reminders/                  ← module folder = feature
│   │   ├── __init__.py             ← declaration
│   │   └── routes.py               ← API endpoints
│   ├── notes/
│   │   ├── __init__.py
│   │   └── routes.py
│   ├── agenda/
│   │   ├── __init__.py
│   │   └── routes.py
│   └── scheduler/                  ← scheduler management API
│       ├── __init__.py
│       └── routes.py
│
├── clark.json                      ← one source of truth
├── app.py                          ← 3 lines
├── migrations/                     ← core migrations only
├── data/                           ← SQLite
├── docs/
│   ├── coding-philosophy.md        ← development guide
│   └── agent-integration.md        ← agent's guide
├── scripts/
├── deploy/
├── tests/
└── pyproject.toml
```

---

## Config Architecture

### One File: `clark.json`

All settings in one JSON file. No `.env`. No scattered config.

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
    "scheduler": { "enabled": true },
    "weather": {
      "enabled": false,
      "city": "Jakarta"
    }
  }
}
```

### Config Merging

```
Module declares:  config_defaults = {"enabled": false, "city": "Jakarta", "unit": "celsius"}
clark.json:       "weather": { "enabled": true, "city": "Surabaya" }

Merged result:    {"enabled": true, "city": "Surabaya", "unit": "celsius"}
```

- Module provides **defaults**
- `clark.json` provides **overrides**
- Values in `clark.json` win
- Module always has complete config, even without clark.json entries

### Hot Reload

```bash
curl -X POST http://localhost:8124/api/reload
```

Reload behavior:
1. Reads `clark.json` fresh
2. Compares module configs to current state
3. Enables newly-enabled modules (calls `on_load`)
4. Disables newly-disabled modules (calls `on_unload`)
5. Updates running module configs
6. **Running jobs are not interrupted**

---

## Module Lifecycle

### Discovery (on startup)

```
create_app()
├── core.module_manager.discover()
│   ├── Scan modules/*/__init__.py for Module subclasses
│   ├── For each found:
│   │   ├── Instantiate module
│   │   ├── Merge config_defaults with clark.json
│   │   ├── Import + register routes (if routes attribute set)
│   │   ├── Register job handlers (if job_handlers attribute set)
│   │   └── Add to registry
│   └── For each enabled module:
│       ├── Run module's migrations (if any)
│       └── Call module.on_load(app)
├── Create scheduler manager
├── Start scheduler loop
└── return app
```

### Hot Reload

```
POST /api/reload
├── Re-read clark.json
├── For each module in registry:
│   ├── If newly enabled → on_load()
│   ├── If newly disabled → on_unload()
│   └── If config changed → update in-memory config
├── For new modules → discover + register
└── Return reload summary
```

---

## The Module Base Class

```python
# core/module.py
from abc import ABC
from typing import Any, Callable


class Module(ABC):
    # ── Declaration fields ──
    name: str = ""
    description: str = ""
    version: str = "0.1.0"

    # Dot-path to routes module (must expose `router` APIRouter)
    routes: str | None = None

    # {job_type: "dot.path.to:handler_func"}
    job_handlers: dict[str, str] = {}

    # Default config values (merged with clark.json)
    config_defaults: dict[str, Any] = {}

    # Migration files (relative to module directory)
    migrations: list[str] = []

    # ── Module's merged config (set by framework on load) ──
    config: dict[str, Any] = {}

    # ── Lifecycle hooks ──
    async def on_load(self, app) -> None:
        """Called when module is enabled."""
        ...

    async def on_unload(self) -> None:
        """Called when module is disabled or app shuts down."""
        ...

    async def on_health(self) -> dict:
        """Return health metrics."""
        return {}
```

---

## Phase 2: Convert Built-ins to Modules

### What Changes

| Current Location | New Location | Module Name |
|-----------------|--------------|------------|
| `app/api/reminders.py` + Pydantic models | `modules/reminders/routes.py` | `reminders` |
| `app/api/notes.py` + Pydantic models | `modules/notes/routes.py` | `notes` |
| `app/api/agenda.py` + Pydantic models | `modules/agenda/routes.py` | `agenda` |
| `app/api/scheduler.py` + Pydantic models | `modules/scheduler/routes.py` | `scheduler` |
| `app/plugins/scheduler.py` | `modules/scheduler/__init__.py` | merged |
| `app/plugins/uptime.py` | `modules/uptime/__init__.py` | `uptime` |

### Execution Order

```
Phase 2a: Create Module base class + ModuleManager in core/
Phase 2b: Convert reminders → modules/reminders/
Phase 2c: Convert notes → modules/notes/
Phase 2d: Convert agenda → modules/agenda/
Phase 2e: Convert scheduler API + SchedulerPlugin → modules/scheduler/
Phase 2f: Convert uptime → modules/uptime/
Phase 2g: Remove app/plugins/ directory
Phase 2h: Remove app/api/ directory (all gone)
Phase 2i: Implement clark.json config
Phase 2j: Implement hot reload endpoint
Phase 2k: Remove .env — all config to clark.json
Phase 2l: Clean up app/ re-export shims
```

### After Phase 2

- `core/` is the only framework code
- `modules/` is the only place features live
- `app/` is gone
- `app.py` is 3 lines: `from core.app import create_app; app = create_app()`
- `clark.json` is the only config file

---

## Phase 3: Auto-Discovery

- `ModuleManager.discover()` scans `modules/*/__init__.py`
- All modules registered through discovery, not manual code
- Add a new feature: `mkdir modules/weather` + 3 files + edit `clark.json`
- Core never changes

---

## Phase 4: Event Hooks (Future)

- `on_before_job_execute`, `on_after_job_execute`, `on_job_error`
- Cross-module hooks (e.g., agenda module fires event that notes module listens to)
- Plugin config auto-loaded from `clark.json` via module name namespace

---

## Backward Compatibility

| Endpoint | Phase 2 | Phase 3 | Phase 4 |
|----------|---------|---------|---------|
| `POST /api/reminders` | ✅ | ✅ | ✅ |
| `GET /api/reminders` | ✅ | ✅ | ✅ |
| `POST /api/notes` | ✅ | ✅ | ✅ |
| `GET /api/agenda` | ✅ | ✅ | ✅ |
| `POST /api/scheduler/jobs` | ✅ | ✅ | ✅ |
| `GET /api/health` | ✅ | ✅ | ✅ |

**No API breaks.** Only internal structure changes.

---

## Code Size Target

| Component | Current | Target |
|-----------|---------|--------|
| `core/` (framework) | ~500 lines | ~500 lines |
| `modules/` (built-ins) | 0 lines | ~1,000 lines |
| `app/` | ~2,000 lines | 0 lines (removed) |
| New feature from scratch | 7 edits across core | **3 files in module folder** |

---

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| Import paths break during conversion | Keep `app/` re-export shims until all modules converted |
| Module discovery misses module | Explicit `modules` key in `clark.json` as fallback |
| Migration files scatter across modules | Each module's migrations tracked in `_module_schema` table |
| Hot reload breaks running state | Hot reload only touches module config; scheduling loop keeps running |
| Backward compat broken | Convert one module at a time, test after each |
