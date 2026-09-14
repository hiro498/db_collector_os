-- PHASE 13: External SERP / AI Search Observation Layer.
-- Purely additive: does not ALTER or DROP any table from 0001-0004.
--
-- Naming note: migration 0002 already created `ci_serp_queries` /
-- `ci_serp_results` as bare future-extension placeholders (see
-- repository/future.py::SerpRepository, future/serp_engine.py) with no
-- country/language/device/observed_at breakdown and nothing ever wrote to
-- them. Reusing that exact table name here would either silently no-op
-- against the old (incompatible) schema via `CREATE TABLE IF NOT EXISTS`,
-- or require an ALTER TABLE against a baseline migration -- both worse
-- than just using new, non-colliding names. `ci_serp_queries`/
-- `ci_serp_results` are left completely untouched; this phase's tables
-- are the ones actually read/written from here on.
--
-- Design rule (spec section 2): internal readiness
-- (ci_ai_page_analysis.ai_citation_readiness_score, from PHASE 12) and
-- external reality (everything in this file) are NEVER stored in the same
-- table. ci_ai_page_analysis is not touched by this migration at all --
-- the "reality" rollup lives entirely in the new ci_ai_page_visibility
-- table, computed by observation/pipeline.py from the raw tables below.
-- A NULL column here always means "not observed", never "observed as 0".

-- ---------------------------------------------------------------------------
-- Organic SERP observation
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ci_serp_observations (
    serp_observation_id TEXT PRIMARY KEY,
    query                TEXT NOT NULL,
    keyword_id           TEXT REFERENCES ci_keywords(keyword_id),
    country              TEXT NOT NULL DEFAULT 'JP',
    language             TEXT NOT NULL DEFAULT 'ja',
    device               TEXT NOT NULL DEFAULT 'desktop',
    observed_at          TEXT NOT NULL,
    provider             TEXT NOT NULL,
    status               TEXT NOT NULL,  -- available|unavailable|blocked|error
    response_hash        TEXT,
    raw_reference         TEXT,
    created_at             TEXT NOT NULL,
    UNIQUE(query, country, language, device, observed_at, provider)
);
CREATE INDEX IF NOT EXISTS idx_ci_serp_observations_keyword ON ci_serp_observations(keyword_id);
CREATE INDEX IF NOT EXISTS idx_ci_serp_observations_query ON ci_serp_observations(query, country, language, device);

CREATE TABLE IF NOT EXISTS ci_serp_observation_results (
    serp_result_id       TEXT PRIMARY KEY,
    serp_observation_id  TEXT NOT NULL REFERENCES ci_serp_observations(serp_observation_id),
    result_position       INTEGER NOT NULL,
    result_url             TEXT NOT NULL,
    normalized_url          TEXT NOT NULL,
    result_domain            TEXT NOT NULL,
    title                     TEXT,
    snippet                    TEXT,
    result_type                 TEXT NOT NULL DEFAULT 'organic'  -- organic|video|image|news|forum|shopping|other
);
CREATE INDEX IF NOT EXISTS idx_ci_serp_observation_results_obs ON ci_serp_observation_results(serp_observation_id);
CREATE INDEX IF NOT EXISTS idx_ci_serp_observation_results_url ON ci_serp_observation_results(normalized_url);

-- ---------------------------------------------------------------------------
-- AI Overviews observation (kept structurally separate from AI Mode --
-- spec section 7: "must not be forced into the same table")
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ci_aio_observations (
    aio_observation_id TEXT PRIMARY KEY,
    query               TEXT NOT NULL,
    keyword_id          TEXT REFERENCES ci_keywords(keyword_id),
    country             TEXT NOT NULL DEFAULT 'JP',
    language            TEXT NOT NULL DEFAULT 'ja',
    device              TEXT NOT NULL DEFAULT 'desktop',
    observed_at         TEXT NOT NULL,
    provider            TEXT NOT NULL,
    status              TEXT NOT NULL,
    aio_present         INTEGER,  -- NULL unless status='available'
    aio_text_hash       TEXT,
    citation_count      INTEGER NOT NULL DEFAULT 0,
    response_hash       TEXT,
    raw_reference       TEXT,
    created_at          TEXT NOT NULL,
    UNIQUE(query, country, language, device, observed_at, provider)
);
CREATE INDEX IF NOT EXISTS idx_ci_aio_observations_keyword ON ci_aio_observations(keyword_id);
CREATE INDEX IF NOT EXISTS idx_ci_aio_observations_query ON ci_aio_observations(query, country, language, device);

CREATE TABLE IF NOT EXISTS ci_aio_citations (
    aio_citation_id       TEXT PRIMARY KEY,
    aio_observation_id    TEXT NOT NULL REFERENCES ci_aio_observations(aio_observation_id),
    citation_position     INTEGER,
    citation_url          TEXT NOT NULL,
    normalized_url        TEXT NOT NULL,
    citation_domain       TEXT NOT NULL,
    citation_anchor_text  TEXT,
    citation_context      TEXT,
    citation_source_type  TEXT
);
CREATE INDEX IF NOT EXISTS idx_ci_aio_citations_obs ON ci_aio_citations(aio_observation_id);
CREATE INDEX IF NOT EXISTS idx_ci_aio_citations_url ON ci_aio_citations(normalized_url);

-- ---------------------------------------------------------------------------
-- AI Mode observation (structurally independent of AIO)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ci_ai_mode_observations (
    ai_mode_observation_id TEXT PRIMARY KEY,
    query                   TEXT NOT NULL,
    keyword_id              TEXT REFERENCES ci_keywords(keyword_id),
    country                 TEXT NOT NULL DEFAULT 'JP',
    language                TEXT NOT NULL DEFAULT 'ja',
    device                  TEXT NOT NULL DEFAULT 'desktop',
    observed_at             TEXT NOT NULL,
    provider                TEXT NOT NULL,
    status                  TEXT NOT NULL,
    response_hash           TEXT,
    citation_count          INTEGER NOT NULL DEFAULT 0,
    raw_reference           TEXT,
    created_at              TEXT NOT NULL,
    UNIQUE(query, country, language, device, observed_at, provider)
);
CREATE INDEX IF NOT EXISTS idx_ci_ai_mode_observations_keyword ON ci_ai_mode_observations(keyword_id);
CREATE INDEX IF NOT EXISTS idx_ci_ai_mode_observations_query ON ci_ai_mode_observations(query, country, language, device);

CREATE TABLE IF NOT EXISTS ci_ai_mode_citations (
    ai_mode_citation_id    TEXT PRIMARY KEY,
    ai_mode_observation_id TEXT NOT NULL REFERENCES ci_ai_mode_observations(ai_mode_observation_id),
    citation_position      INTEGER,
    citation_url           TEXT NOT NULL,
    normalized_url         TEXT NOT NULL,
    citation_domain        TEXT NOT NULL,
    citation_anchor_text   TEXT,
    citation_context       TEXT
);
CREATE INDEX IF NOT EXISTS idx_ci_ai_mode_citations_obs ON ci_ai_mode_citations(ai_mode_observation_id);
CREATE INDEX IF NOT EXISTS idx_ci_ai_mode_citations_url ON ci_ai_mode_citations(normalized_url);

-- ---------------------------------------------------------------------------
-- Fan-out observation (reuses ci_ai_fanout_queries candidates from PHASE 12)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ci_fanout_observations (
    fanout_observation_id TEXT PRIMARY KEY,
    fanout_query_id        TEXT NOT NULL REFERENCES ci_ai_fanout_queries(fanout_query_id),
    parent_query             TEXT NOT NULL,
    fanout_query               TEXT NOT NULL,
    fanout_intent                TEXT NOT NULL,
    country                        TEXT NOT NULL DEFAULT 'JP',
    language                        TEXT NOT NULL DEFAULT 'ja',
    device                            TEXT NOT NULL DEFAULT 'desktop',
    observed_at                        TEXT NOT NULL,
    provider                            TEXT NOT NULL,
    status                                TEXT NOT NULL,
    target_page_id                        TEXT REFERENCES ci_pages(page_id),
    target_rank                            INTEGER,
    target_cited                            INTEGER,
    result_urls_json                         TEXT NOT NULL DEFAULT '[]',
    response_hash                             TEXT,
    raw_reference                              TEXT,
    created_at                                  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ci_fanout_observations_query ON ci_fanout_observations(fanout_query_id);
CREATE INDEX IF NOT EXISTS idx_ci_fanout_observations_page ON ci_fanout_observations(target_page_id);

-- ---------------------------------------------------------------------------
-- Readiness vs Reality rollup + opportunity signals (spec sections 10-11).
-- One row per page; computed entirely from the observation tables above
-- (never from ci_ai_page_analysis's readiness score directly writing here,
-- and never the other way around).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ci_ai_page_visibility (
    page_id                        TEXT PRIMARY KEY REFERENCES ci_pages(page_id),
    crawl_run_id                   TEXT NOT NULL REFERENCES ci_crawl_runs(crawl_run_id),

    organic_rank                   INTEGER,
    organic_top3                   INTEGER,
    organic_top10                  INTEGER,
    organic_top20                  INTEGER,
    organic_top100                 INTEGER,
    organic_observed_at            TEXT,

    aio_cited                      INTEGER,
    aio_citation_position          INTEGER,
    aio_first_seen                 TEXT,
    aio_last_seen                  TEXT,
    aio_observation_count          INTEGER NOT NULL DEFAULT 0,
    aio_citation_count             INTEGER NOT NULL DEFAULT 0,
    aio_citation_frequency         REAL,
    aio_persistence_score          REAL,

    ai_mode_cited                  INTEGER,
    ai_mode_citation_position      INTEGER,
    ai_mode_first_seen             TEXT,
    ai_mode_last_seen              TEXT,
    ai_mode_observation_count      INTEGER NOT NULL DEFAULT 0,
    ai_mode_citation_count         INTEGER NOT NULL DEFAULT 0,
    ai_mode_citation_frequency     REAL,
    ai_mode_persistence_score      REAL,

    fanout_queries_total           INTEGER NOT NULL DEFAULT 0,
    fanout_queries_observed        INTEGER NOT NULL DEFAULT 0,
    fanout_top10_count             INTEGER NOT NULL DEFAULT 0,
    fanout_top20_count             INTEGER NOT NULL DEFAULT 0,
    fanout_citation_count          INTEGER NOT NULL DEFAULT 0,
    fanout_visibility_rate         REAL,

    readiness_vs_reality_class     TEXT,  -- A|B|C|D, spec section 10; NULL if reality unknown
    organic_aio_cross_class        TEXT,  -- e.g. organic_top10_aio_cited; NULL if inputs unknown

    signal_high_readiness_not_cited          INTEGER,
    signal_low_rank_but_cited                INTEGER,
    signal_high_rank_not_cited               INTEGER,
    signal_fanout_visible_not_root_visible   INTEGER,
    signal_aio_only                          INTEGER,
    signal_ai_mode_only                      INTEGER,
    signal_aio_and_ai_mode                   INTEGER,
    signal_organic_only                      INTEGER,

    computed_at                    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ci_ai_page_visibility_run ON ci_ai_page_visibility(crawl_run_id);
CREATE INDEX IF NOT EXISTS idx_ci_ai_page_visibility_class ON ci_ai_page_visibility(readiness_vs_reality_class);

-- ---------------------------------------------------------------------------
-- Offline/import provenance (spec section 15: duplicate-import protection
-- + "provider/observation_type/observed_at/query/country/device must be
-- preserved"). The observation tables' own UNIQUE constraints are what
-- actually prevent a duplicate *row*; this table is the human-facing
-- import audit log (what file, when, how many rows/duplicates/errors).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ci_observation_import_batches (
    import_batch_id           TEXT PRIMARY KEY,
    file_path                 TEXT NOT NULL,
    file_hash                 TEXT NOT NULL,
    provider                  TEXT,
    observation_type          TEXT NOT NULL,  -- organic|aio|ai_mode|fanout|gsc
    imported_count            INTEGER NOT NULL DEFAULT 0,
    skipped_duplicate_count   INTEGER NOT NULL DEFAULT 0,
    error_count                INTEGER NOT NULL DEFAULT 0,
    imported_at                 TEXT NOT NULL,
    UNIQUE(file_hash, observation_type)
);

-- ---------------------------------------------------------------------------
-- Google Search Console adapter skeleton (spec section 17). No OAuth/
-- credential/production wiring in this phase -- this table only exists so
-- manually-exported GSC data can be imported and joined against pages.
-- `data_source_category` keeps ordinary Search data separable from any
-- future Generative-AI-specific GSC reporting without a schema change.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ci_gsc_observations (
    gsc_observation_id     TEXT PRIMARY KEY,
    gsc_query              TEXT NOT NULL,
    gsc_page               TEXT NOT NULL,
    normalized_page        TEXT NOT NULL,
    country                TEXT,
    device                 TEXT,
    data_source_category   TEXT NOT NULL DEFAULT 'search',  -- search|generative_ai
    impressions            INTEGER,
    clicks                 INTEGER,
    ctr                    REAL,
    position               REAL,
    observed_date           TEXT NOT NULL,
    created_at               TEXT NOT NULL,
    UNIQUE(gsc_query, normalized_page, country, device, observed_date, data_source_category)
);
CREATE INDEX IF NOT EXISTS idx_ci_gsc_observations_page ON ci_gsc_observations(normalized_page);
