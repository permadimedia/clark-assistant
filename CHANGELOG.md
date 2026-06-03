# Changelog

---

## v0.7.0 (2026-06-03)

### New: Email Automation Module (Phase 1)

Full inbox scanning, classification, and Telegram notification module.
Provider-agnostic — first implementation uses Gmail API (`gmail.metadata` scope).

#### Module Structure
- `EmailEngine` — orchestrator: connect → scan → classify → notify
- `EmailMessage` dataclass — metadata only (from, subject, date, snippet)
- `GmailProvider` — OAuth 2.0, token refresh, inbox/draft listing
- `classifier.py` — rule-based classification by subject keywords + sender domain
- `formatter.py` — Telegram-friendly notification text
- `labels.py` — label definitions (priority: `!`, archive: `_`)
- `routes.py` — 5 REST endpoints
- `handler.py` — daily scheduler job handler
- `classifier_rules.json` — editable rules separate from code

#### Email Tracking Database
- Self-contained SQLite at `~/.clark/email.db` (not coupled to core clark DB)
- `email_messages` table: tracks message_id, is_new, notified, first/last seen, classification
- `email_scan_log` table: audit trail with duration, counts, errors
- Dedup by message_id: first scan = new; subsequent scans = seen
- Local search queries this DB (instant, no API call)

#### Smart Notifications
- Only first-seen items in 🆕 NEW section; older unread in 📌 OLDER UNREAD
- Priority ordering: security > billing > account > followup > archive
- Summary footer with counts
- Once notified, messages are marked and don't re-appear

#### Improved Classifier (Trained on 50 Real Emails)
- English + Indonesian keywords (voucher, diskon, pembayaran, berhasil, kode verifikasi)
- GitHub token/2FA emails correctly classified as priority_security
- Subject keywords checked before domain fallback
- 0 unclassified in sample (50/50 labeled)

#### API Endpoints
| Method | Route | Description |
|--------|-------|-------------|
| `GET` | `/api/email/status` | Provider status + DB stats + scan history |
| `POST` | `/api/email/scan` | Trigger scan — dedup, classify, notify |
| `GET` | `/api/email/search?q=...` | Instant local search (no API call) |
| `POST` | `/api/email/notified` | Mark scanned emails as notified |
| `POST` | `/api/email/cleanup` | Delete drafts / archive old (opt-in write mode) |

#### Privacy & Security
- Read-only by default (`read_only: true`)
- Metadata only — no body content, no attachments, no sent mail
- Credentials stored at `~/.config/email/` (outside repo)
- Separate DB keeps email data isolated from core

#### Tests
- 43/43 unit tests pass
- Real Gmail UAT: dedup confirmed (scan 1: 50 new; scan 2: 0 new, 50 seen)
- Integration tests: module discovery, routes, handlers

### Documentation
- `docs/email-automation.md` — complete setup guide with architecture, API reference, config, troubleshooting
- `README.md` updated with email automation API table + config example
- `openclaw/skills/clark/SKILL.md` — agent rules, search/notified flow, dedup
- `proposals/` — email-automation proposal + tracking design docs

---

## v0.3.0 (2026-05-26)

### Agentic Architecture (Phase 1 + 2)
- Removed all v0.2 dead code: local intent detection, pending state, picker, JSON action parsing
- Removed confirmation flows (Ask class, _validate_and_route, _handle_missing_params)
- Removed callback query / inline keyboard handling
- Single agentic flow: all non-command messages → Gemini → TOOL: call → execute → respond
- Gemini's conversational text preserved alongside tool results (no more robotic responses)
- Tool handlers never return None (always user-friendly error message)

### Agentic Notes (3 New Tools)
- `note_search(query)` — FTS5 search existing notes via Gemini
- `note_update(id, text)` — update note content
- `note_delete(id)` — delete a note
- Prompt updated with semantic guidelines: remind = notification, note = documentation

### Context Memory Rewrite
- Replaced paired user↔bot system with last-10 raw messages (unfiltered)
- Commands (/agenda, /notes, etc.) no longer filtered as noise
- FTS5 demoted to supplement (recent messages always prioritized)
- No orphan message drops

### Mobile-First UI
- Shorter separators (35→20 chars) and cleaner formatting
- Removed redundant icons (🔔, redundant ✅, duplicate markdown bold)
- Compact time format: "Wed 28 May · 09:00 WIB"
- Notes: no code blocks in preview, date-grouped list (Recent / Older)
- Help: 35→20 lines, compact grouped by function
- Notes preview: first line only, no raw newlines

### Cost Tracking
- Token usage logged per request from Gemini usageMetadata (100% accurate)
- `/cost` command — inline cost report in IDR
- Monthly projection, avg tokens/req, rate table
- Detects expensive model usage (flash vs flash-lite)

### Model Change
- Default: gemini-2.5-flash → gemini-2.5-flash-lite (75% cheaper)
- `.env.example` updated accordingly

### Bug Fixes
- FTS5 queries: `SELECT id` → `SELECT rowid as id` (external content tables)
- Timezone: `/reminders` displayed 7h behind due to naive datetime handling
- Markdown 400 on edit: `_edit_message_text` now retries as plain text
- Notes with `#` prefix no longer crash Markdown parsing

### Files Removed
- `app/plugins/brain/state.py` — pending state module
- `app/plugins/brain/picker.py` — inline keyboard time picker
- `tests/test_plugins/test_state.py`

### Files Added
- `app/cost_tracker.py` — token logging + report generation
- `migrations/010_token_usage.sql` — token usage table
- `scripts/cost_report.py` — CLI cost report

## v0.2.0 (2026-05-25)

### Context-Aware Memory
- Conversation context retrieval (20 recent msgs + FTS5 search + notes)
- User↔bot message pairing for full conversation context
- Noise filtering (commands excluded from context)
- Thinking indicator ("⏳ Wait, I'm thinking…" → edit with answer)

### Agenda System
- `/agenda` — Today's agenda with ☐/☑ visual markers
- `/agenda tomorrow` — Tomorrow's agenda
- `/agenda all` — All upcoming grouped by date
- `/done <id>` — Mark item done
- Auto-send: daily at 06:00 (today) and 16:00 (tomorrow)
- Agenda is a UI/UX layer over reminders (no separate storage)

### Local Intent Detection (Confidence Scoring)
- 12 features: Agenda, Remind, Notes, Search, PC Control, Help
- Bilingual (EN + ID + mixed language)
- Confidence scoring 0.0-1.0 with ambiguity detection
- No-API fast path for common queries
- 30+ test patterns, typos normalized directly in keyword sets

### Performance
- Reminder scheduler: 30s → 5min (10× fewer wake-ups)
- Query filter: only load reminders due within 2 hours
- Auto-cleanup expired reminders (>7 days)
- Composite index for scheduler queries

### Bug Fixes
- Reminder date format: ISO 8601 broke SQLite comparison (migration 009)
- Naive vs aware datetime comparison crash
- "besok" without hour → TypeError
- Agenda today/tomorrow ambiguity with "tomorrow" keyword
- start-bot.sh: `source .env` space handling, grep exit code, stale env vars
- start-bot.sh: DNS wait before webhook registration

### Security
- Pre-commit hook with detect-secrets
- Hardcoded IP removed from ping-pc.sh
- `.env` parsing safety

### Tests
- 3 → 66 tests (unit + integration + live audit)
- 50 local intent detection pattern tests
- Live UAT script (scripts/audit_bot.py)

### Documentation
- AGENTS.md: full architecture, local intent matrix
- README.md: deployment modes, features, context-aware memory
- INFORMATION.md: complete feature tracker

---

## v0.1.0 (2026-05-17)

Initial release:
- Telegram webhook server
- 6 LLM providers (Gemini, Anthropic, OpenAI, OpenRouter, OpenCode, Zen)
- Plugin system: System, WebSearch, Reminder, Notes, Summarizer, ScriptRunner
- BrainPlugin v2: natural language → JSON → route
- PC Power Control via GPIO relay
- BrainPlugin v3: actions[] array, validation gates, confirmation flow
- Cloudflare Quick Tunnel + Named Tunnel support
- systemd deployment service
- 3 tests
