-- DB Collector OS - initial schema
-- SQLite. Applied by db_collector_os.database.migrate()

CREATE TABLE IF NOT EXISTS schema_migrations (
    version     TEXT PRIMARY KEY,
    applied_at  TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- Job Registry
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS jobs (
    job_id           TEXT PRIMARY KEY,
    job_name         TEXT NOT NULL,
    category         TEXT NOT NULL,
    target_db        TEXT NOT NULL,
    target_table     TEXT NOT NULL,
    collector_type   TEXT NOT NULL,      -- official_site | local_business | person | api
    adapter          TEXT NOT NULL,      -- adapter module/class name
    priority         INTEGER NOT NULL DEFAULT 50,
    enabled          INTEGER NOT NULL DEFAULT 1,
    phase            TEXT NOT NULL DEFAULT 'bootstrap',
    schedule         TEXT NOT NULL DEFAULT '@hourly',
    max_pages        INTEGER NOT NULL DEFAULT 200,
    max_depth        INTEGER NOT NULL DEFAULT 3,
    concurrency      INTEGER NOT NULL DEFAULT 2,
    rate_limit       REAL NOT NULL DEFAULT 1.0,   -- seconds between requests per domain
    config_json      TEXT NOT NULL DEFAULT '{}',
    status           TEXT NOT NULL DEFAULT 'idle',
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    last_started_at  TEXT,
    last_finished_at TEXT,
    next_run_at      TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_next_run_at ON jobs(next_run_at);
CREATE INDEX IF NOT EXISTS idx_jobs_enabled ON jobs(enabled);

-- ---------------------------------------------------------------------------
-- Entity Candidates (discovery output, not yet accepted into entities)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS entity_candidates (
    candidate_id     TEXT PRIMARY KEY,
    job_id           TEXT NOT NULL REFERENCES jobs(job_id),
    entity_type      TEXT NOT NULL,
    name             TEXT,
    normalized_name  TEXT,
    url              TEXT,
    source_url       TEXT,
    discovery_method TEXT,
    fingerprint      TEXT,
    confidence       REAL NOT NULL DEFAULT 0.5,
    status           TEXT NOT NULL DEFAULT 'new',  -- new|accepted|duplicate|rejected|review
    discovered_at    TEXT NOT NULL,
    reviewed_at      TEXT
);
CREATE INDEX IF NOT EXISTS idx_candidates_job ON entity_candidates(job_id);
CREATE INDEX IF NOT EXISTS idx_candidates_status ON entity_candidates(status);
CREATE INDEX IF NOT EXISTS idx_candidates_fingerprint ON entity_candidates(fingerprint);

-- ---------------------------------------------------------------------------
-- Fetch Queue
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fetch_queue (
    queue_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id           TEXT NOT NULL REFERENCES jobs(job_id),
    url              TEXT NOT NULL,
    domain           TEXT NOT NULL,
    priority         INTEGER NOT NULL DEFAULT 50,
    status           TEXT NOT NULL DEFAULT 'queued', -- queued|fetching|done|failed|skipped
    attempt_count    INTEGER NOT NULL DEFAULT 0,
    max_attempts     INTEGER NOT NULL DEFAULT 5,
    last_http_status INTEGER,
    next_retry_at    TEXT,
    fetched_at       TEXT,
    content_hash     TEXT,
    etag             TEXT,
    last_modified    TEXT,
    error_message    TEXT,
    created_at       TEXT NOT NULL,
    UNIQUE(job_id, url)
);
CREATE INDEX IF NOT EXISTS idx_fetchq_job ON fetch_queue(job_id);
CREATE INDEX IF NOT EXISTS idx_fetchq_status ON fetch_queue(status);
CREATE INDEX IF NOT EXISTS idx_fetchq_domain ON fetch_queue(domain);
CREATE INDEX IF NOT EXISTS idx_fetchq_next_retry ON fetch_queue(next_retry_at);

-- ---------------------------------------------------------------------------
-- Domain rate limiting state
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS domain_rate_limits (
    domain           TEXT PRIMARY KEY,
    delay_seconds    REAL NOT NULL DEFAULT 1.0,
    concurrency      INTEGER NOT NULL DEFAULT 2,
    last_request_at  TEXT,
    blocked_until     TEXT,
    error_count      INTEGER NOT NULL DEFAULT 0
);

-- ---------------------------------------------------------------------------
-- Entities (accepted, canonical records)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS entities (
    entity_id        TEXT PRIMARY KEY,
    job_id           TEXT NOT NULL REFERENCES jobs(job_id),
    entity_type      TEXT NOT NULL,
    name             TEXT,
    normalized_name  TEXT,
    canonical_url    TEXT,
    domain           TEXT,
    address          TEXT,
    telephone        TEXT,
    external_id      TEXT,
    fingerprint      TEXT,
    data_json        TEXT NOT NULL DEFAULT '{}',
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    deleted_at       TEXT
);
CREATE INDEX IF NOT EXISTS idx_entities_job ON entities(job_id);
CREATE INDEX IF NOT EXISTS idx_entities_fingerprint ON entities(fingerprint);
CREATE INDEX IF NOT EXISTS idx_entities_normalized_name ON entities(normalized_name);
CREATE INDEX IF NOT EXISTS idx_entities_domain ON entities(domain);
CREATE INDEX IF NOT EXISTS idx_entities_external_id ON entities(external_id);

-- ---------------------------------------------------------------------------
-- Evidence / Provenance
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS evidence (
    evidence_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id        TEXT NOT NULL REFERENCES entities(entity_id),
    field            TEXT NOT NULL,
    value            TEXT,
    source_url       TEXT NOT NULL,
    fetched_at       TEXT NOT NULL,
    confidence       REAL NOT NULL DEFAULT 0.5
);
CREATE INDEX IF NOT EXISTS idx_evidence_entity ON evidence(entity_id);
CREATE INDEX IF NOT EXISTS idx_evidence_field ON evidence(entity_id, field);

-- ---------------------------------------------------------------------------
-- Review Queue
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS review_queue (
    review_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id           TEXT NOT NULL REFERENCES jobs(job_id),
    entity_id        TEXT,
    candidate_id     TEXT,
    reason           TEXT NOT NULL,
    details          TEXT,
    status           TEXT NOT NULL DEFAULT 'open', -- open|resolved|dismissed
    created_at       TEXT NOT NULL,
    resolved_at      TEXT
);
CREATE INDEX IF NOT EXISTS idx_review_job ON review_queue(job_id);
CREATE INDEX IF NOT EXISTS idx_review_status ON review_queue(status);

-- ---------------------------------------------------------------------------
-- Run History
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS run_history (
    run_id           TEXT PRIMARY KEY,
    job_id           TEXT NOT NULL REFERENCES jobs(job_id),
    started_at       TEXT NOT NULL,
    finished_at      TEXT,
    status           TEXT NOT NULL DEFAULT 'running', -- running|completed|failed|aborted
    discovered_count INTEGER NOT NULL DEFAULT 0,
    fetched_count    INTEGER NOT NULL DEFAULT 0,
    inserted_count   INTEGER NOT NULL DEFAULT 0,
    updated_count    INTEGER NOT NULL DEFAULT 0,
    duplicate_count  INTEGER NOT NULL DEFAULT 0,
    review_count     INTEGER NOT NULL DEFAULT 0,
    error_count      INTEGER NOT NULL DEFAULT 0,
    duration_seconds REAL
);
CREATE INDEX IF NOT EXISTS idx_run_history_job ON run_history(job_id);

-- ---------------------------------------------------------------------------
-- Discovery saturation tracking
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS discovery_runs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id              TEXT NOT NULL REFERENCES jobs(job_id),
    run_id              TEXT NOT NULL,
    discovered_total    INTEGER NOT NULL DEFAULT 0,
    new_candidates      INTEGER NOT NULL DEFAULT 0,
    duplicate_candidates INTEGER NOT NULL DEFAULT 0,
    accepted            INTEGER NOT NULL DEFAULT 0,
    rejected            INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_discovery_runs_job ON discovery_runs(job_id, created_at);

-- ---------------------------------------------------------------------------
-- Daily Metrics
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS daily_metrics (
    date             TEXT PRIMARY KEY,
    new_entities     INTEGER NOT NULL DEFAULT 0,
    updated_entities INTEGER NOT NULL DEFAULT 0,
    fetch_success    INTEGER NOT NULL DEFAULT 0,
    fetch_errors     INTEGER NOT NULL DEFAULT 0,
    review_count     INTEGER NOT NULL DEFAULT 0,
    jobs_executed    INTEGER NOT NULL DEFAULT 0,
    runtime_seconds  REAL NOT NULL DEFAULT 0,
    pages_fetched    INTEGER NOT NULL DEFAULT 0
);

-- ---------------------------------------------------------------------------
-- Checkpoints (resume state per job)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS checkpoints (
    job_id           TEXT PRIMARY KEY REFERENCES jobs(job_id),
    run_id           TEXT,
    phase            TEXT,
    state_json       TEXT NOT NULL DEFAULT '{}',
    updated_at       TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- Worker heartbeats
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS workers (
    worker_id        TEXT PRIMARY KEY,
    hostname         TEXT,
    pid              INTEGER,
    status           TEXT NOT NULL DEFAULT 'idle', -- idle|busy|stopped
    current_job_id   TEXT,
    started_at       TEXT NOT NULL,
    last_heartbeat   TEXT NOT NULL
);
