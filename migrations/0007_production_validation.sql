-- PHASE 15: Real-Data Production Validation / Target Keyword Discovery.
-- Purely additive: does not touch 0001-0006. This phase integrates
-- PHASE 3-14's existing engines end-to-end; it introduces no new scoring
-- model of its own -- these tables only persist the site-wide rollup and
-- the PHASE 14 Opportunity integration the CLI/Web layer needs to render
-- a run's results, plus a run header. ci_site_profiles (migration 0002)
-- remains the coarse per-domain totals table; it is not duplicated here.

CREATE TABLE IF NOT EXISTS ci_validation_runs (
    validation_run_id            TEXT PRIMARY KEY,
    crawl_run_id                 TEXT REFERENCES ci_crawl_runs(crawl_run_id),
    domain_id                    TEXT REFERENCES ci_domains(domain_id),
    target_url                   TEXT NOT NULL,
    our_domain_run_id            TEXT REFERENCES ci_crawl_runs(crawl_run_id),
    max_pages                    INTEGER,
    rate_limit_delay_seconds     REAL,
    output_dir                   TEXT,
    status                       TEXT NOT NULL,  -- RUNNING | COMPLETED | FAILED
    production_validation_status TEXT,           -- PASS | CONDITIONAL_PASS | FAIL (set once COMPLETED)
    top50_ab_rate                REAL,
    top50_ab_rate_is_human_audited INTEGER NOT NULL DEFAULT 0,
    summary_json                 TEXT,
    started_at                   TEXT NOT NULL,
    completed_at                 TEXT,
    error_message                TEXT
);
CREATE INDEX IF NOT EXISTS idx_ci_validation_runs_domain ON ci_validation_runs(domain_id);
CREATE INDEX IF NOT EXISTS idx_ci_validation_runs_status ON ci_validation_runs(status);

-- Site-wide keyword aggregation (spec section 8): one row per distinct
-- normalized_keyword discovered anywhere in the validated crawl_run,
-- rolled up from the existing per-page ci_page_keywords/ci_keyword_occurrences
-- rows PHASE 1 already computed -- never a re-derivation of the underlying
-- per-page scores.
CREATE TABLE IF NOT EXISTS ci_domain_keyword_summary (
    summary_id             TEXT PRIMARY KEY,
    validation_run_id      TEXT NOT NULL REFERENCES ci_validation_runs(validation_run_id),
    keyword                TEXT NOT NULL,
    normalized_keyword     TEXT NOT NULL,
    keyword_id             TEXT REFERENCES ci_keywords(keyword_id),
    pages_count            INTEGER NOT NULL DEFAULT 0,
    page_types_json        TEXT NOT NULL DEFAULT '[]',
    best_keyword_score     INTEGER NOT NULL DEFAULT 0,
    avg_keyword_score      REAL NOT NULL DEFAULT 0,
    total_occurrences      INTEGER NOT NULL DEFAULT 0,
    title_occurrences      INTEGER NOT NULL DEFAULT 0,
    h1_occurrences         INTEGER NOT NULL DEFAULT 0,
    heading_occurrences    INTEGER NOT NULL DEFAULT 0,
    body_occurrences       INTEGER NOT NULL DEFAULT 0,
    anchor_occurrences     INTEGER NOT NULL DEFAULT 0,
    site_structure_score   REAL NOT NULL DEFAULT 0,
    cross_page_score       REAL NOT NULL DEFAULT 0,

    cluster_id             TEXT,
    cluster_is_representative INTEGER NOT NULL DEFAULT 1,

    primary_intent         TEXT,
    secondary_intents_json TEXT NOT NULL DEFAULT '[]',
    intent_confidence      TEXT,  -- HIGH | MEDIUM | LOW

    commercial_score       REAL,
    transactional_signal   INTEGER NOT NULL DEFAULT 0,
    comparison_signal      INTEGER NOT NULL DEFAULT 0,
    review_signal          INTEGER NOT NULL DEFAULT 0,
    ranking_signal         INTEGER NOT NULL DEFAULT 0,
    price_signal           INTEGER NOT NULL DEFAULT 0,
    affiliate_relevance    REAL,
    monetization_score     REAL,
    money_keyword_class    TEXT,  -- HIGH | MEDIUM | LOW

    is_noise               INTEGER NOT NULL DEFAULT 0,
    noise_reason           TEXT,

    -- machine-computed quality signal (spec section 10): never an
    -- LLM-authored label -- purely thresholds on the columns above.
    audit_class_auto       TEXT,  -- A | B | C | D
    -- human review fields (spec section 31): populated only via explicit
    -- human-audit CLI/DB action, never written by the pipeline itself.
    audit_class            TEXT,
    audit_note             TEXT,

    computed_at            TEXT NOT NULL,
    UNIQUE(validation_run_id, normalized_keyword)
);
CREATE INDEX IF NOT EXISTS idx_ci_domain_keyword_summary_run ON ci_domain_keyword_summary(validation_run_id);
CREATE INDEX IF NOT EXISTS idx_ci_domain_keyword_summary_score ON ci_domain_keyword_summary(best_keyword_score);

-- Target Keyword Priority ranking (spec sections 18-19, 23): the PHASE 15
-- deliverable. Every *_score/observation field here is populated by
-- calling into PHASE 12/13/14 as-is (never a new scoring formula) --
-- NULL whenever that phase has nothing to report for this keyword.
CREATE TABLE IF NOT EXISTS ci_target_keyword_priorities (
    priority_id                TEXT PRIMARY KEY,
    validation_run_id          TEXT NOT NULL REFERENCES ci_validation_runs(validation_run_id),
    priority_rank               INTEGER NOT NULL,
    keyword                      TEXT NOT NULL,
    normalized_keyword           TEXT NOT NULL,
    keyword_id                    TEXT REFERENCES ci_keywords(keyword_id),

    intent                         TEXT,
    commercial_score                REAL,
    money_keyword_class              TEXT,

    competitor_usage_strength         REAL,   -- best competitor's ci_opportunity_components-style strength proxy
    competitor_page_count              INTEGER,
    best_competitor_page_id             TEXT REFERENCES ci_pages(page_id),
    best_competitor_page_url             TEXT,
    best_competitor_score                 REAL,

    ai_readiness                           INTEGER,  -- PHASE 12 ai_citation_readiness_score of best competitor page
    organic_rank                            INTEGER,  -- PHASE 13, NULL = NOT_OBSERVED
    aio_cited                                INTEGER,
    ai_mode_cited                             INTEGER,
    citation_frequency                         REAL,
    fanout_visibility                           REAL,

    content_gap_score                            REAL,   -- PHASE 14
    opportunity_score                             REAL,   -- PHASE 14 overall_opportunity_score
    score_status                                   TEXT,
    confidence_label                                TEXT,
    confidence_value                                 REAL,
    top_reason_code                                   TEXT,
    top_reason_text                                    TEXT,
    recommended_action                                  TEXT,

    demand_status                                        TEXT,  -- OBSERVED | UNAVAILABLE
    search_volume                                          INTEGER,
    trend                                                   TEXT,
    cpc                                                      REAL,
    competition                                              REAL,

    blue_ocean_candidate                                      INTEGER,  -- 1/0/NULL
    blue_ocean_candidate_status                                TEXT,     -- OK | INSUFFICIENT_DATA

    computed_at                                                 TEXT NOT NULL,
    UNIQUE(validation_run_id, normalized_keyword)
);
CREATE INDEX IF NOT EXISTS idx_ci_target_keyword_priorities_run ON ci_target_keyword_priorities(validation_run_id);
CREATE INDEX IF NOT EXISTS idx_ci_target_keyword_priorities_rank ON ci_target_keyword_priorities(validation_run_id, priority_rank);
