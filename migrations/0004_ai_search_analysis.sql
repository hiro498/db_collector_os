-- PHASE 12: AI Search Citation / Reference Analysis.
-- Purely additive: does not touch 0001_init.sql, 0002_competitive_intelligence.sql,
-- or 0003_keyword_occurrence_span.sql. New ci_ai_* tables only.
--
-- Score-field NULL semantics (spec section 3): organic_visibility_score,
-- aio_citation_score, ai_mode_citation_score, fanout_coverage_score, and
-- source_affinity_score all require an external observation this P0 cannot
-- perform (SERP, AI Overviews, AI Mode, Preferred Sources) -- they are left
-- NULL by every write path in this phase, never defaulted to 0. Application
-- code must never conflate "0" (observed and scored zero) with NULL
-- ("not observed"). ai_search_total_score is likewise NULL whenever any of
-- those four axes is unavailable, since summing across a partially-missing
-- 7-axis model would misrepresent what was actually measured. The always-
-- computable counterpart is ai_citation_readiness_score (0-100), built only
-- from signals this phase can measure locally.

CREATE TABLE IF NOT EXISTS ci_ai_page_analysis (
    page_id                        TEXT PRIMARY KEY REFERENCES ci_pages(page_id),
    crawl_run_id                   TEXT NOT NULL REFERENCES ci_crawl_runs(crawl_run_id),

    -- section 3: seven independent axis scores + the combined total.
    organic_visibility_score       REAL,
    aio_citation_score             REAL,
    ai_mode_citation_score         REAL,
    fanout_coverage_score          REAL,
    proprietary_information_score  INTEGER,
    evidence_freshness_score       INTEGER,
    source_affinity_score          REAL,
    ai_search_total_score          REAL,

    -- always-computable substitute for ai_search_total_score (section 20).
    ai_citation_readiness_score    INTEGER,

    -- section 4: proprietary / primary information signals.
    primary_source_signal          INTEGER NOT NULL DEFAULT 0,
    firsthand_signal                INTEGER NOT NULL DEFAULT 0,
    proprietary_data_signal         INTEGER NOT NULL DEFAULT 0,
    derived_metric_count            INTEGER NOT NULL DEFAULT 0,
    unique_fact_count                INTEGER NOT NULL DEFAULT 0,
    verifiable_fact_count             INTEGER NOT NULL DEFAULT 0,
    sample_size_mentions               INTEGER NOT NULL DEFAULT 0,
    methodology_signal                  INTEGER NOT NULL DEFAULT 0,
    source_traceability_score            INTEGER NOT NULL DEFAULT 0,

    -- section 5: numeric fact aggregates (individual facts in ci_ai_numeric_facts).
    numeric_fact_count               INTEGER NOT NULL DEFAULT 0,
    derived_numeric_fact_count       INTEGER NOT NULL DEFAULT 0,
    comparison_numeric_fact_count    INTEGER NOT NULL DEFAULT 0,
    ratio_percentage_count           INTEGER NOT NULL DEFAULT 0,
    ranking_numeric_fact_count       INTEGER NOT NULL DEFAULT 0,
    sample_size_count                INTEGER NOT NULL DEFAULT 0,
    numeric_fact_quality_score       INTEGER NOT NULL DEFAULT 0,

    -- section 6: comparison information (individual rows in ci_ai_comparisons).
    comparison_entity_count          INTEGER NOT NULL DEFAULT 0,
    comparison_dimension_count       INTEGER NOT NULL DEFAULT 0,
    normalized_comparison_signal     INTEGER NOT NULL DEFAULT 0,
    same_condition_comparison_signal INTEGER NOT NULL DEFAULT 0,
    derived_comparison_metric_count  INTEGER NOT NULL DEFAULT 0,
    comparison_source_traceability   INTEGER NOT NULL DEFAULT 0,
    comparison_information_score     INTEGER NOT NULL DEFAULT 0,

    -- section 7: evidence freshness (individual events in ci_ai_freshness_events).
    published_at                     TEXT,
    modified_at                      TEXT,
    data_updated_at                  TEXT,
    freshness_timestamp_score        INTEGER NOT NULL DEFAULT 0,
    evidence_change_score            INTEGER NOT NULL DEFAULT 0,
    meaningful_update_signal         INTEGER NOT NULL DEFAULT 0,

    -- section 8: AIO extractability.
    answer_in_first_100_words        INTEGER NOT NULL DEFAULT 0,
    key_fact_in_first_100_words      INTEGER NOT NULL DEFAULT 0,
    comparison_result_near_top       INTEGER NOT NULL DEFAULT 0,
    summary_near_top                 INTEGER NOT NULL DEFAULT 0,
    aio_extractability_score         INTEGER NOT NULL DEFAULT 0,

    -- section 9: AI Mode structure (citation readiness, not a citation claim).
    subtopic_count                   INTEGER NOT NULL DEFAULT 0,
    related_question_count           INTEGER NOT NULL DEFAULT 0,
    entity_coverage_count            INTEGER NOT NULL DEFAULT 0,
    evidence_block_count             INTEGER NOT NULL DEFAULT 0,
    ai_mode_content_coverage_score   INTEGER NOT NULL DEFAULT 0,

    -- section 10: fan-out CONTENT coverage (internal; candidates in
    -- ci_ai_fanout_queries). Distinct from fanout_coverage_score above,
    -- which is the external/SERP-dependent axis and stays NULL.
    fanout_content_coverage_score    INTEGER NOT NULL DEFAULT 0,

    -- section 11: source preference / brand affinity internal proxies.
    site_author_identity_signal      INTEGER NOT NULL DEFAULT 0,
    editorial_policy_signal          INTEGER NOT NULL DEFAULT 0,
    about_page_signal                INTEGER NOT NULL DEFAULT 0,
    contact_transparency_signal      INTEGER NOT NULL DEFAULT 0,
    source_citation_consistency      INTEGER NOT NULL DEFAULT 0,
    repeat_entity_coverage           INTEGER NOT NULL DEFAULT 0,
    topic_specialization_signal      INTEGER NOT NULL DEFAULT 0,
    source_transparency_score        INTEGER NOT NULL DEFAULT 0,
    external_source_preference_status TEXT,

    -- section 12: organic visibility (external; NULL until SERP is wired up).
    organic_rank                     INTEGER,
    organic_top10                    INTEGER,
    organic_top20                    INTEGER,
    serp_observed_at                 TEXT,

    -- section 13: AIO / AI Mode citation observation summary (external;
    -- raw per-observation rows live in ci_ai_citation_observations. All
    -- NULL until a future adapter populates them).
    aio_cited                        INTEGER,
    aio_citation_position            INTEGER,
    aio_observed_at                  TEXT,
    ai_mode_cited                    INTEGER,
    ai_mode_citation_position        INTEGER,
    ai_mode_observed_at              TEXT,
    citation_first_seen              TEXT,
    citation_last_seen               TEXT,
    citation_observation_count       INTEGER,
    citation_persistence_score       REAL,

    extractor_version                 TEXT NOT NULL,
    computed_at                        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ci_ai_page_analysis_run ON ci_ai_page_analysis(crawl_run_id);
CREATE INDEX IF NOT EXISTS idx_ci_ai_page_analysis_readiness ON ci_ai_page_analysis(ai_citation_readiness_score);

-- section 5 + 15: individual numeric-fact evidence.
CREATE TABLE IF NOT EXISTS ci_ai_numeric_facts (
    fact_id           TEXT PRIMARY KEY,
    page_id           TEXT NOT NULL REFERENCES ci_pages(page_id),
    fact_type         TEXT NOT NULL,  -- numeric|derived|comparison|ratio_percentage|ranking|sample_size
    signal_value      TEXT,
    source_text       TEXT,
    html_element      TEXT,
    page_section      TEXT,
    confidence        REAL NOT NULL DEFAULT 0.5,
    extractor_version TEXT NOT NULL,
    created_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ci_ai_numeric_facts_page ON ci_ai_numeric_facts(page_id);
CREATE INDEX IF NOT EXISTS idx_ci_ai_numeric_facts_type ON ci_ai_numeric_facts(page_id, fact_type);

-- section 6 + 15: individual comparison-structure evidence.
CREATE TABLE IF NOT EXISTS ci_ai_comparisons (
    comparison_id      TEXT PRIMARY KEY,
    page_id            TEXT NOT NULL REFERENCES ci_pages(page_id),
    structure_type     TEXT NOT NULL,  -- table|list|card|heading|body
    entity_count       INTEGER NOT NULL DEFAULT 0,
    dimension_count    INTEGER NOT NULL DEFAULT 0,
    normalized         INTEGER NOT NULL DEFAULT 0,
    same_condition     INTEGER NOT NULL DEFAULT 0,
    source_text        TEXT,
    html_element       TEXT,
    confidence         REAL NOT NULL DEFAULT 0.5,
    extractor_version  TEXT NOT NULL,
    created_at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ci_ai_comparisons_page ON ci_ai_comparisons(page_id);

-- section 10 + 15: fan-out subquery candidates (query fan-out simulation).
CREATE TABLE IF NOT EXISTS ci_ai_fanout_queries (
    fanout_query_id     TEXT PRIMARY KEY,
    page_id             TEXT NOT NULL REFERENCES ci_pages(page_id),
    base_keyword        TEXT NOT NULL,
    subquery_text       TEXT NOT NULL,
    intent_class        TEXT NOT NULL,  -- informational|comparison|price|review|ranking|brand|local|howto|problem_solving
    covered_by_content  INTEGER NOT NULL DEFAULT 0,
    serp_observed       INTEGER,  -- NULL until external SERP is wired up (section 10: never inferred)
    created_at          TEXT NOT NULL,
    UNIQUE(page_id, subquery_text)
);
CREATE INDEX IF NOT EXISTS idx_ci_ai_fanout_queries_page ON ci_ai_fanout_queries(page_id);
CREATE INDEX IF NOT EXISTS idx_ci_ai_fanout_queries_intent ON ci_ai_fanout_queries(intent_class);

-- section 13: raw AIO / AI Mode citation observations -- schema-only in
-- this phase; nothing in this codebase writes a row here yet (see
-- future/aio_observation.py, future/ai_mode_observation.py).
CREATE TABLE IF NOT EXISTS ci_ai_citation_observations (
    citation_observation_id TEXT PRIMARY KEY,
    page_id                 TEXT NOT NULL REFERENCES ci_pages(page_id),
    surface                 TEXT NOT NULL,  -- aio|ai_mode
    cited                   INTEGER NOT NULL,
    citation_position       INTEGER,
    citation_text           TEXT,
    observed_at             TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ci_ai_citation_observations_page ON ci_ai_citation_observations(page_id, surface);

-- section 7 + 15: individual freshness / "before -> after" evidence events.
CREATE TABLE IF NOT EXISTS ci_ai_freshness_events (
    freshness_event_id TEXT PRIMARY KEY,
    page_id             TEXT NOT NULL REFERENCES ci_pages(page_id),
    event_type          TEXT NOT NULL,  -- review_delta|ranking_delta|price_delta|inventory_delta|new_item_delta|before_after_text
    before_value        TEXT,
    after_value         TEXT,
    source_text          TEXT,
    html_element          TEXT,
    confidence             REAL NOT NULL DEFAULT 0.5,
    extractor_version       TEXT NOT NULL,
    created_at               TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ci_ai_freshness_events_page ON ci_ai_freshness_events(page_id);
