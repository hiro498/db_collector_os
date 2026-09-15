-- PHASE 14: Opportunity Score / Cross-Competitor Comparison.
-- Purely additive: does not touch 0001-0005. New ci_* tables only.
--
-- Design note (spec section 2/22): every "gap" or "opportunity" score here
-- is derived either from a real external observation (PHASE 13's
-- ci_serp_observation_results / ci_aio_citations / ci_ai_mode_citations /
-- ci_fanout_observations -- availability=OBSERVED) or from a real
-- comparison of our own already-crawled content against a competitor's
-- already-crawled content (PHASE 12's ci_ai_page_analysis fields --
-- availability=INFERRED, since it's a genuine computation over real
-- crawled data, just not an external ground-truth measurement). A
-- component is only ever UNAVAILABLE (never 0/false) when neither exists.
-- ci_opportunity_components stores that availability explicitly per
-- component so no score here can be mistaken for a confident 0.

CREATE TABLE IF NOT EXISTS ci_keyword_metrics (
    keyword_metric_id    TEXT PRIMARY KEY,
    query                TEXT NOT NULL,
    search_volume        INTEGER,
    impressions          INTEGER,
    clicks               INTEGER,
    ctr                  REAL,
    trend                TEXT,
    seasonality          TEXT,
    related_query_count  INTEGER,
    cpc                  REAL,
    competition          REAL,
    source               TEXT NOT NULL,
    observed_at          TEXT NOT NULL,
    created_at           TEXT NOT NULL,
    UNIQUE(source, query, observed_at)
);
CREATE INDEX IF NOT EXISTS idx_ci_keyword_metrics_query ON ci_keyword_metrics(query);

-- One row per (entity_type, entity_id) -- 'keyword' or 'page' -- carrying
-- the section-3 top-level aggregate scores plus score_status/confidence.
-- Component-level detail (value/weight/evidence/availability) lives
-- separately in ci_opportunity_components; this table never stores a
-- final number without that backing detail existing alongside it.
CREATE TABLE IF NOT EXISTS ci_opportunity_analyses (
    opportunity_id              TEXT PRIMARY KEY,
    entity_type                 TEXT NOT NULL,  -- 'keyword' | 'page'
    entity_id                   TEXT NOT NULL,
    crawl_run_id                TEXT REFERENCES ci_crawl_runs(crawl_run_id),
    our_page_id                 TEXT REFERENCES ci_pages(page_id),

    keyword_opportunity_score   REAL,
    page_opportunity_score      REAL,
    ai_opportunity_score        REAL,
    fanout_opportunity_score    REAL,
    commercial_opportunity_score REAL,
    content_gap_score           REAL,
    overall_opportunity_score   REAL,

    score_status                TEXT NOT NULL,  -- COMPLETE | PARTIAL | INTERNAL_ONLY | NOT_ENOUGH_DATA
    confidence_label             TEXT NOT NULL, -- HIGH | MEDIUM | LOW
    confidence_value             REAL NOT NULL, -- 0-1

    organic_ai_divergence_score  REAL,
    organic_ai_divergence_class  TEXT,

    -- section 5 keyword-specific fields (NULL for entity_type='page')
    query                        TEXT,
    intent                       TEXT,
    competitor_count             INTEGER,
    best_competitor_rank         INTEGER,
    best_competitor_page_id      TEXT REFERENCES ci_pages(page_id),
    our_rank                     INTEGER,
    rank_gap                     INTEGER,
    aio_competitors_cited        INTEGER,
    ai_mode_competitors_cited    INTEGER,
    our_aio_cited                INTEGER,
    our_ai_mode_cited            INTEGER,

    computed_at                  TEXT NOT NULL,
    UNIQUE(entity_type, entity_id, our_page_id)
);
CREATE INDEX IF NOT EXISTS idx_ci_opportunity_analyses_entity ON ci_opportunity_analyses(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_ci_opportunity_analyses_overall ON ci_opportunity_analyses(overall_opportunity_score);
CREATE INDEX IF NOT EXISTS idx_ci_opportunity_analyses_run ON ci_opportunity_analyses(crawl_run_id);

-- Individual component scores (spec section 4): never collapse to just the
-- final number above. component_name is one of demand_score,
-- competition_score, organic_gap_score, ai_gap_score, fanout_gap_score,
-- content_gap_score, proprietary_gap_score, freshness_gap_score,
-- commercial_score, monetization_score, source_strength_gap_score.
CREATE TABLE IF NOT EXISTS ci_opportunity_components (
    component_id     TEXT PRIMARY KEY,
    opportunity_id    TEXT NOT NULL REFERENCES ci_opportunity_analyses(opportunity_id),
    component_name    TEXT NOT NULL,
    value              REAL,             -- NULL when availability='UNAVAILABLE'
    weight             REAL NOT NULL,     -- the configured/renormalized weight actually used
    availability       TEXT NOT NULL,     -- OBSERVED | INFERRED | UNAVAILABLE
    evidence           TEXT,
    computed_at        TEXT NOT NULL,
    UNIQUE(opportunity_id, component_name)
);
CREATE INDEX IF NOT EXISTS idx_ci_opportunity_components_opportunity ON ci_opportunity_components(opportunity_id);

-- Pairwise comparisons (spec section 7): page-vs-page, domain-vs-domain,
-- keyword-vs-keyword, all through one generic shape.
CREATE TABLE IF NOT EXISTS ci_competitor_comparisons (
    comparison_id          TEXT PRIMARY KEY,
    left_entity_type       TEXT NOT NULL,   -- 'page' | 'domain' | 'keyword'
    left_entity_id         TEXT NOT NULL,
    right_entity_type      TEXT NOT NULL,
    right_entity_id        TEXT NOT NULL,
    comparison_dimension   TEXT NOT NULL,
    left_value             REAL,
    right_value            REAL,
    gap_value               REAL,
    winner                  TEXT NOT NULL,  -- left | right | tie | unknown
    confidence               TEXT NOT NULL, -- HIGH | MEDIUM | LOW
    evidence                  TEXT,
    computed_at                TEXT NOT NULL,
    UNIQUE(left_entity_type, left_entity_id, right_entity_type, right_entity_id, comparison_dimension)
);
CREATE INDEX IF NOT EXISTS idx_ci_competitor_comparisons_left ON ci_competitor_comparisons(left_entity_type, left_entity_id);
CREATE INDEX IF NOT EXISTS idx_ci_competitor_comparisons_right ON ci_competitor_comparisons(right_entity_type, right_entity_id);

-- Content gap detail (spec section 9), one row per (our page, competitor page).
CREATE TABLE IF NOT EXISTS ci_content_gaps (
    content_gap_id                TEXT PRIMARY KEY,
    our_page_id                    TEXT NOT NULL REFERENCES ci_pages(page_id),
    competitor_page_id              TEXT NOT NULL REFERENCES ci_pages(page_id),
    missing_keywords_json            TEXT NOT NULL DEFAULT '[]',
    missing_subtopics_json           TEXT NOT NULL DEFAULT '[]',
    missing_entities_json            TEXT NOT NULL DEFAULT '[]',
    missing_questions_json           TEXT NOT NULL DEFAULT '[]',
    missing_numeric_facts_json       TEXT NOT NULL DEFAULT '[]',
    missing_comparison_dimensions_json TEXT NOT NULL DEFAULT '[]',
    missing_primary_information_json TEXT NOT NULL DEFAULT '[]',
    missing_freshness_evidence_json  TEXT NOT NULL DEFAULT '[]',
    missing_internal_link_topics_json TEXT NOT NULL DEFAULT '[]',
    content_gap_score                 REAL NOT NULL,
    computed_at                        TEXT NOT NULL,
    UNIQUE(our_page_id, competitor_page_id)
);
CREATE INDEX IF NOT EXISTS idx_ci_content_gaps_our_page ON ci_content_gaps(our_page_id);

-- Reason Engine output (spec sections 17-18).
CREATE TABLE IF NOT EXISTS ci_opportunity_reasons (
    reason_id            TEXT PRIMARY KEY,
    opportunity_id        TEXT NOT NULL REFERENCES ci_opportunity_analyses(opportunity_id),
    reason_code            TEXT NOT NULL,
    reason_text             TEXT NOT NULL,
    impact_score              REAL NOT NULL,
    evidence_reference          TEXT,
    computed_at                  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ci_opportunity_reasons_opportunity ON ci_opportunity_reasons(opportunity_id);
CREATE INDEX IF NOT EXISTS idx_ci_opportunity_reasons_code ON ci_opportunity_reasons(reason_code);

-- Action recommendations (spec section 19) -- codes and targets only, no
-- generated article/body text of any kind.
CREATE TABLE IF NOT EXISTS ci_opportunity_actions (
    action_id       TEXT PRIMARY KEY,
    opportunity_id   TEXT NOT NULL REFERENCES ci_opportunity_analyses(opportunity_id),
    action_code       TEXT NOT NULL,
    priority           TEXT NOT NULL,  -- HIGH | MEDIUM | LOW
    reason_code         TEXT,
    target_page          TEXT REFERENCES ci_pages(page_id),
    target_keyword         TEXT REFERENCES ci_keywords(keyword_id),
    computed_at              TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ci_opportunity_actions_opportunity ON ci_opportunity_actions(opportunity_id);
