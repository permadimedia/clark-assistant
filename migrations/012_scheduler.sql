-- 012_scheduler.sql
-- Scheduler manager — cron_jobs + job_runs tables

CREATE TABLE IF NOT EXISTS cron_jobs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    description     TEXT DEFAULT '',
    job_type        TEXT NOT NULL,  -- 'send_message', 'send_agenda', 'reminder_alert'
    schedule_type   TEXT NOT NULL,  -- 'cron', 'interval', 'once'
    schedule_config TEXT NOT NULL,  -- JSON
    payload         TEXT NOT NULL,  -- JSON
    enabled         INTEGER DEFAULT 1,
    max_retries     INTEGER DEFAULT 0,
    retry_delay_s   INTEGER DEFAULT 60,
    last_run_at     TEXT,
    next_run_at     TEXT,
    run_count       INTEGER DEFAULT 0,
    created_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS job_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id      INTEGER NOT NULL REFERENCES cron_jobs(id),
    status      TEXT NOT NULL,  -- 'running' | 'success' | 'failed' | 'skipped'
    started_at  TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    finished_at TEXT,
    error       TEXT,
    result      TEXT,
    attempt     INTEGER DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_cron_jobs_next ON cron_jobs(enabled, next_run_at);
CREATE INDEX IF NOT EXISTS idx_job_runs_job  ON job_runs(job_id, started_at);
