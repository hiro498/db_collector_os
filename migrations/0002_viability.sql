-- DB Collector OS - DB viability assessment tool schema.
-- Additive only: no existing table is touched. See db_collector_os/viability/.
--
-- Traceability: every table below hangs off `db_ideas` (which candidate DB
-- theme) and, from `keyword_metrics` onward, off `evaluation_runs` (when /
-- which run). `source` columns record where a number came from
-- (keyword_planner|rakko|csv_import|gemini_supplement|manual|serp_api|...).
-- Nothing is ever overwritten in place: re-investigation inserts new rows
-- under a new run_id so history is preserved.

CREATE TABLE IF NOT EXISTS db_ideas (
    idea_id      TEXT PRIMARY KEY,
    theme_name   TEXT NOT NULL,
    category     TEXT,
    notes        TEXT,
    status       TEXT NOT NULL DEFAULT 'new',   -- new|evaluating|go|hold|no_go
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_db_ideas_status ON db_ideas(status);

-- ---------------------------------------------------------------------------
-- Evaluation runs: one row per Phase 1/Phase 2 investigation pass.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS evaluation_runs (
    run_id       TEXT PRIMARY KEY,
    idea_id      TEXT NOT NULL REFERENCES db_ideas(idea_id),
    phase        TEXT NOT NULL DEFAULT 'phase1', -- phase1|phase2|complete
    status       TEXT NOT NULL DEFAULT 'running', -- running|completed|failed
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    notes        TEXT
);
CREATE INDEX IF NOT EXISTS idx_eval_runs_idea ON evaluation_runs(idea_id, started_at);

-- ---------------------------------------------------------------------------
-- Keyword candidates: the structured search-axis keyword universe for a theme.
-- Not run-scoped -- the candidate list itself is theme state; metrics
-- (below) are what get re-collected per run.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS keyword_candidates (
    candidate_id   TEXT PRIMARY KEY,
    idea_id        TEXT NOT NULL REFERENCES db_ideas(idea_id),
    keyword        TEXT NOT NULL,
    is_main        INTEGER NOT NULL DEFAULT 0,
    axis_json      TEXT NOT NULL DEFAULT '{}',
    created_at     TEXT NOT NULL,
    UNIQUE(idea_id, keyword)
);
CREATE INDEX IF NOT EXISTS idx_kw_candidates_idea ON keyword_candidates(idea_id);

-- ---------------------------------------------------------------------------
-- Keyword metrics: monthly search volume + related figures, per source, per run.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS keyword_metrics (
    metric_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id          TEXT NOT NULL REFERENCES keyword_candidates(candidate_id),
    run_id                TEXT REFERENCES evaluation_runs(run_id),
    monthly_search_volume INTEGER,
    source                TEXT NOT NULL,
    competition           REAL,
    low_bid               REAL,
    high_bid              REAL,
    trend                 TEXT,
    collected_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_kw_metrics_candidate ON keyword_metrics(candidate_id, collected_at);
CREATE INDEX IF NOT EXISTS idx_kw_metrics_run ON keyword_metrics(run_id);

-- ---------------------------------------------------------------------------
-- Phase 1 demand summary: one row per run, theme-level aggregation + gate result.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS demand_summaries (
    summary_id             TEXT PRIMARY KEY,
    run_id                 TEXT NOT NULL REFERENCES evaluation_runs(run_id),
    idea_id                TEXT NOT NULL REFERENCES db_ideas(idea_id),
    total_search_volume    INTEGER NOT NULL DEFAULT 0,
    main_kw_volume         INTEGER NOT NULL DEFAULT 0,
    longtail_kw_count      INTEGER NOT NULL DEFAULT 0,
    kw_with_volume_count   INTEGER NOT NULL DEFAULT 0,
    kw_zero_or_low_count   INTEGER NOT NULL DEFAULT 0,
    dispersion             REAL,
    top_keywords_json      TEXT NOT NULL DEFAULT '[]',
    phase1_result          TEXT NOT NULL,   -- PASS|FAIL
    reasoning              TEXT NOT NULL,
    created_at             TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_demand_summaries_run ON demand_summaries(run_id);
CREATE INDEX IF NOT EXISTS idx_demand_summaries_idea ON demand_summaries(idea_id, created_at);

-- ---------------------------------------------------------------------------
-- Phase 2: SERP queries actually issued, and the results captured for each.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS serp_queries (
    query_id       TEXT PRIMARY KEY,
    run_id         TEXT NOT NULL REFERENCES evaluation_runs(run_id),
    candidate_id   TEXT NOT NULL REFERENCES keyword_candidates(candidate_id),
    query_text     TEXT NOT NULL,
    source         TEXT NOT NULL,
    collected_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_serp_queries_run ON serp_queries(run_id);
CREATE INDEX IF NOT EXISTS idx_serp_queries_candidate ON serp_queries(candidate_id);

CREATE TABLE IF NOT EXISTS serp_results (
    result_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    query_id       TEXT NOT NULL REFERENCES serp_queries(query_id),
    rank           INTEGER NOT NULL,
    title          TEXT,
    url            TEXT,
    domain         TEXT,
    snippet        TEXT,
    site_type      TEXT,      -- optional manual/heuristic classification override
    page_type      TEXT,      -- optional manual/heuristic classification override
    title_match    TEXT,      -- optional override: exact|partial|none
    db_type_page   INTEGER,   -- optional override: 1/0
    intent_satisfied INTEGER, -- optional override: 1/0
    collected_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_serp_results_query ON serp_results(query_id, rank);

-- ---------------------------------------------------------------------------
-- Per-keyword competition strength (WEAK/MEDIUM/STRONG) derived from a query's results.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS keyword_competition (
    competition_id          TEXT PRIMARY KEY,
    run_id                  TEXT NOT NULL REFERENCES evaluation_runs(run_id),
    candidate_id            TEXT NOT NULL REFERENCES keyword_candidates(candidate_id),
    query_id                TEXT NOT NULL REFERENCES serp_queries(query_id),
    strength                TEXT NOT NULL,   -- WEAK|MEDIUM|STRONG
    strength_score          REAL NOT NULL,
    intent_satisfied         INTEGER NOT NULL DEFAULT 0,
    db_type_page_present     INTEGER NOT NULL DEFAULT 0,
    site_type_summary_json   TEXT NOT NULL DEFAULT '{}',
    reasoning                TEXT NOT NULL,
    created_at               TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_kw_competition_run ON keyword_competition(run_id);
CREATE INDEX IF NOT EXISTS idx_kw_competition_candidate ON keyword_competition(candidate_id, created_at);

-- ---------------------------------------------------------------------------
-- Final per-run evaluation: scores + GO/HOLD/NO-GO + human-readable reasoning.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS db_idea_evaluations (
    evaluation_id      TEXT PRIMARY KEY,
    run_id              TEXT NOT NULL REFERENCES evaluation_runs(run_id),
    idea_id             TEXT NOT NULL REFERENCES db_ideas(idea_id),
    demand_score        REAL NOT NULL,
    competition_score   REAL NOT NULL,
    db_fit_score        REAL NOT NULL,
    priority_score       REAL NOT NULL,
    weak_ratio           REAL,
    medium_ratio         REAL,
    strong_ratio         REAL,
    winnable_demand       REAL,
    unwinnable_demand     REAL,
    final_judgement       TEXT NOT NULL,   -- GO|HOLD|NO-GO
    reasoning             TEXT NOT NULL,
    created_at            TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_idea_evals_run ON db_idea_evaluations(run_id);
CREATE INDEX IF NOT EXISTS idx_idea_evals_idea ON db_idea_evaluations(idea_id, created_at);
