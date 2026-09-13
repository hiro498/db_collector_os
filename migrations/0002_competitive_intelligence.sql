-- Competitive Keyword / Content Discovery Engine (CORE + VERTICAL)
-- Purely additive: does not ALTER or DROP anything from 0001_init.sql.
-- All tables are prefixed `ci_` to keep this bounded context visually
-- separate from the original entity-collection schema it lives alongside.

-- ---------------------------------------------------------------------------
-- CORE: domains / crawl runs / crawl urls
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ci_domains (
    domain_id        TEXT PRIMARY KEY,
    domain           TEXT NOT NULL UNIQUE,
    vertical         TEXT NOT NULL DEFAULT 'general',
    target_type      TEXT NOT NULL DEFAULT 'affiliate_domain',
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ci_crawl_runs (
    crawl_run_id          TEXT PRIMARY KEY,
    domain_id             TEXT NOT NULL REFERENCES ci_domains(domain_id),
    input_url              TEXT NOT NULL,
    requested_mode          TEXT NOT NULL,
    input_mode                TEXT NOT NULL,
    vertical                    TEXT NOT NULL DEFAULT 'general',
    status                        TEXT NOT NULL DEFAULT 'discovered',
    stop_requested                  INTEGER NOT NULL DEFAULT 0,
    started_at                        TEXT NOT NULL,
    finished_at                        TEXT,
    discovered_total                    INTEGER NOT NULL DEFAULT 0,
    sitemap_discovered                    INTEGER NOT NULL DEFAULT 0,
    internal_discovered                     INTEGER NOT NULL DEFAULT 0,
    attempted_total                           INTEGER NOT NULL DEFAULT 0,
    fetched_success                             INTEGER NOT NULL DEFAULT 0,
    js_fallback_success                           INTEGER NOT NULL DEFAULT 0,
    canonical_duplicate                             INTEGER NOT NULL DEFAULT 0,
    noindex_count                                     INTEGER NOT NULL DEFAULT 0,
    robots_blocked                                      INTEGER NOT NULL DEFAULT 0,
    count_404                                             INTEGER NOT NULL DEFAULT 0,
    count_other_4xx                                         INTEGER NOT NULL DEFAULT 0,
    count_5xx                                                 INTEGER NOT NULL DEFAULT 0,
    count_timeout                                               INTEGER NOT NULL DEFAULT 0,
    count_retry_failed                                            INTEGER NOT NULL DEFAULT 0,
    excluded_count                                                  INTEGER NOT NULL DEFAULT 0,
    analyzed_pages                                                    INTEGER NOT NULL DEFAULT 0,
    unresolved_count                                                    INTEGER NOT NULL DEFAULT 0,
    converged                                                             INTEGER NOT NULL DEFAULT 0,
    completion_rate                                                         REAL NOT NULL DEFAULT 0.0,
    sitemap_phase_done             INTEGER NOT NULL DEFAULT 0,
    sitemap_index_phase_done       INTEGER NOT NULL DEFAULT 0,
    internal_link_phase_done       INTEGER NOT NULL DEFAULT 0,
    pagination_phase_done          INTEGER NOT NULL DEFAULT 0,
    site_aggregation_done          INTEGER NOT NULL DEFAULT 0,
    error_message                  TEXT
);
CREATE INDEX IF NOT EXISTS idx_ci_crawl_runs_domain ON ci_crawl_runs(domain_id);
CREATE INDEX IF NOT EXISTS idx_ci_crawl_runs_status ON ci_crawl_runs(status);

CREATE TABLE IF NOT EXISTS ci_crawl_urls (
    crawl_url_id            TEXT PRIMARY KEY,
    crawl_run_id            TEXT NOT NULL REFERENCES ci_crawl_runs(crawl_run_id),
    domain_id               TEXT NOT NULL REFERENCES ci_domains(domain_id),
    url                     TEXT NOT NULL,
    normalized_url          TEXT NOT NULL,
    discovered_by           TEXT NOT NULL,
    source_url              TEXT,
    crawl_depth             INTEGER NOT NULL DEFAULT 0,
    status                  TEXT NOT NULL DEFAULT 'discovered',
    exclusion_reason        TEXT,
    http_status             INTEGER,
    redirect_to             TEXT,
    canonical_url           TEXT,
    is_canonical_duplicate  INTEGER NOT NULL DEFAULT 0,
    indexable               INTEGER,
    analysis_target         INTEGER NOT NULL DEFAULT 0,
    is_pagination           INTEGER NOT NULL DEFAULT 0,
    fetch_attempts          INTEGER NOT NULL DEFAULT 0,
    error_message           TEXT,
    discovered_at           TEXT NOT NULL,
    updated_at              TEXT NOT NULL,
    UNIQUE(crawl_run_id, normalized_url)
);
CREATE INDEX IF NOT EXISTS idx_ci_crawl_urls_run ON ci_crawl_urls(crawl_run_id);
CREATE INDEX IF NOT EXISTS idx_ci_crawl_urls_run_status ON ci_crawl_urls(crawl_run_id, status);
CREATE INDEX IF NOT EXISTS idx_ci_crawl_urls_normalized ON ci_crawl_urls(normalized_url);

-- ---------------------------------------------------------------------------
-- CORE: pages / page elements
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ci_pages (
    page_id               TEXT PRIMARY KEY,
    crawl_url_id          TEXT NOT NULL REFERENCES ci_crawl_urls(crawl_url_id),
    crawl_run_id          TEXT NOT NULL REFERENCES ci_crawl_runs(crawl_run_id),
    domain_id             TEXT NOT NULL REFERENCES ci_domains(domain_id),
    url                   TEXT NOT NULL,
    normalized_url        TEXT NOT NULL,
    title                 TEXT,
    meta_description      TEXT,
    meta_keywords         TEXT,
    canonical_url         TEXT,
    robots_meta           TEXT,
    page_type             TEXT NOT NULL DEFAULT 'other',
    page_type_confidence  INTEGER NOT NULL DEFAULT 0,
    analysis_target       INTEGER NOT NULL DEFAULT 0,
    monetization_type     TEXT,
    monetization_score    INTEGER NOT NULL DEFAULT 0,
    published_at          TEXT,
    updated_at_source     TEXT,
    raw_html_hash         TEXT,
    fetched_at            TEXT NOT NULL,
    analyzed_at           TEXT,
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ci_pages_run ON ci_pages(crawl_run_id);
CREATE INDEX IF NOT EXISTS idx_ci_pages_domain ON ci_pages(domain_id);
CREATE INDEX IF NOT EXISTS idx_ci_pages_type ON ci_pages(page_type);
CREATE INDEX IF NOT EXISTS idx_ci_pages_normalized ON ci_pages(normalized_url);
CREATE INDEX IF NOT EXISTS idx_ci_pages_crawl_url ON ci_pages(crawl_url_id);

CREATE TABLE IF NOT EXISTS ci_page_elements (
    page_element_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    page_id          TEXT NOT NULL REFERENCES ci_pages(page_id),
    element_type     TEXT NOT NULL,
    position         INTEGER NOT NULL DEFAULT 0,
    text             TEXT,
    attrs_json       TEXT NOT NULL DEFAULT '{}',
    is_boilerplate   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_ci_page_elements_page ON ci_page_elements(page_id);
CREATE INDEX IF NOT EXISTS idx_ci_page_elements_type ON ci_page_elements(page_id, element_type);

-- ---------------------------------------------------------------------------
-- CORE: keywords / scoring / evidence
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ci_keywords (
    keyword_id          TEXT PRIMARY KEY,
    keyword             TEXT NOT NULL,
    normalized_keyword  TEXT NOT NULL UNIQUE,
    token_count         INTEGER NOT NULL DEFAULT 1,
    branded_type        TEXT NOT NULL DEFAULT 'non_branded',
    is_local            INTEGER NOT NULL DEFAULT 0,
    prefecture          TEXT,
    city                TEXT,
    ward                TEXT,
    station             TEXT,
    keyword_class       TEXT NOT NULL DEFAULT 'long_tail',
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ci_keywords_normalized ON ci_keywords(normalized_keyword);

CREATE TABLE IF NOT EXISTS ci_page_keywords (
    page_keyword_id         TEXT PRIMARY KEY,
    page_id                 TEXT NOT NULL REFERENCES ci_pages(page_id),
    keyword_id              TEXT NOT NULL REFERENCES ci_keywords(keyword_id),
    crawl_run_id            TEXT NOT NULL REFERENCES ci_crawl_runs(crawl_run_id),
    score                   INTEGER NOT NULL DEFAULT 0,
    html_score              INTEGER NOT NULL DEFAULT 0,
    content_score           INTEGER NOT NULL DEFAULT 0,
    phrase_score            INTEGER NOT NULL DEFAULT 0,
    site_structure_score    INTEGER NOT NULL DEFAULT 0,
    intent_score            INTEGER NOT NULL DEFAULT 0,
    cross_page_score        INTEGER NOT NULL DEFAULT 0,
    rule_boost              INTEGER NOT NULL DEFAULT 0,
    rule_boost_reasons_json TEXT NOT NULL DEFAULT '[]',
    importance              TEXT NOT NULL DEFAULT 'noise',
    intent                  TEXT,
    intent_group            TEXT,
    commercial_score        INTEGER NOT NULL DEFAULT 0,
    is_primary              INTEGER NOT NULL DEFAULT 0,
    title_hit               INTEGER NOT NULL DEFAULT 0,
    h1_hit                  INTEGER NOT NULL DEFAULT 0,
    h2_count                INTEGER NOT NULL DEFAULT 0,
    h3_count                INTEGER NOT NULL DEFAULT 0,
    body_count              INTEGER NOT NULL DEFAULT 0,
    anchor_count            INTEGER NOT NULL DEFAULT 0,
    computed_at             TEXT NOT NULL,
    UNIQUE(page_id, keyword_id)
);
CREATE INDEX IF NOT EXISTS idx_ci_page_keywords_page ON ci_page_keywords(page_id);
CREATE INDEX IF NOT EXISTS idx_ci_page_keywords_keyword ON ci_page_keywords(keyword_id);
CREATE INDEX IF NOT EXISTS idx_ci_page_keywords_score ON ci_page_keywords(score);
CREATE INDEX IF NOT EXISTS idx_ci_page_keywords_importance ON ci_page_keywords(importance);
CREATE INDEX IF NOT EXISTS idx_ci_page_keywords_intent ON ci_page_keywords(intent);
CREATE INDEX IF NOT EXISTS idx_ci_page_keywords_commercial ON ci_page_keywords(commercial_score);
CREATE INDEX IF NOT EXISTS idx_ci_page_keywords_run ON ci_page_keywords(crawl_run_id);

CREATE TABLE IF NOT EXISTS ci_keyword_occurrences (
    occurrence_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    page_keyword_id   TEXT NOT NULL REFERENCES ci_page_keywords(page_keyword_id),
    element_type      TEXT NOT NULL,
    occurrence_count  INTEGER NOT NULL DEFAULT 1,
    first_position    INTEGER,
    weight            REAL NOT NULL DEFAULT 0.0,
    evidence_text     TEXT
);
CREATE INDEX IF NOT EXISTS idx_ci_keyword_occurrences_pk ON ci_keyword_occurrences(page_keyword_id);

CREATE TABLE IF NOT EXISTS ci_keyword_modifiers (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    page_keyword_id  TEXT NOT NULL REFERENCES ci_page_keywords(page_keyword_id),
    modifier         TEXT NOT NULL,
    UNIQUE(page_keyword_id, modifier)
);
CREATE INDEX IF NOT EXISTS idx_ci_keyword_modifiers_pk ON ci_keyword_modifiers(page_keyword_id);

-- ---------------------------------------------------------------------------
-- CORE: links / CTA
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ci_internal_links (
    internal_link_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    crawl_run_id      TEXT NOT NULL REFERENCES ci_crawl_runs(crawl_run_id),
    source_page_id    TEXT NOT NULL REFERENCES ci_pages(page_id),
    target_url        TEXT NOT NULL,
    target_page_id    TEXT REFERENCES ci_pages(page_id),
    anchor_text       TEXT,
    position          INTEGER NOT NULL DEFAULT 0,
    nofollow          INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_ci_internal_links_source ON ci_internal_links(source_page_id);
CREATE INDEX IF NOT EXISTS idx_ci_internal_links_target ON ci_internal_links(target_page_id);
CREATE INDEX IF NOT EXISTS idx_ci_internal_links_run ON ci_internal_links(crawl_run_id);

CREATE TABLE IF NOT EXISTS ci_outbound_links (
    outbound_link_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    crawl_run_id      TEXT NOT NULL REFERENCES ci_crawl_runs(crawl_run_id),
    source_page_id    TEXT NOT NULL REFERENCES ci_pages(page_id),
    url               TEXT NOT NULL,
    target_domain     TEXT NOT NULL,
    anchor_text       TEXT,
    link_type         TEXT NOT NULL DEFAULT 'other',
    affiliate_network TEXT,
    merchant          TEXT,
    position          INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_ci_outbound_links_source ON ci_outbound_links(source_page_id);
CREATE INDEX IF NOT EXISTS idx_ci_outbound_links_domain ON ci_outbound_links(target_domain);

CREATE TABLE IF NOT EXISTS ci_ctas (
    cta_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    page_id            TEXT NOT NULL REFERENCES ci_pages(page_id),
    cta_text           TEXT,
    target_url         TEXT,
    target_domain      TEXT,
    cta_type           TEXT NOT NULL DEFAULT 'other',
    position           INTEGER NOT NULL DEFAULT 0,
    affiliate_detected INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_ci_ctas_page ON ci_ctas(page_id);

-- ---------------------------------------------------------------------------
-- CORE: clustering / site aggregation
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ci_keyword_clusters (
    cluster_id    TEXT PRIMARY KEY,
    crawl_run_id  TEXT NOT NULL REFERENCES ci_crawl_runs(crawl_run_id),
    label         TEXT,
    method        TEXT NOT NULL DEFAULT 'shared_head_token',
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ci_keyword_clusters_run ON ci_keyword_clusters(crawl_run_id);

CREATE TABLE IF NOT EXISTS ci_keyword_cluster_members (
    cluster_id  TEXT NOT NULL REFERENCES ci_keyword_clusters(cluster_id),
    keyword_id  TEXT NOT NULL REFERENCES ci_keywords(keyword_id),
    PRIMARY KEY (cluster_id, keyword_id)
);

CREATE TABLE IF NOT EXISTS ci_site_profiles (
    domain_id                 TEXT PRIMARY KEY REFERENCES ci_domains(domain_id),
    crawl_run_id              TEXT REFERENCES ci_crawl_runs(crawl_run_id),
    total_pages               INTEGER NOT NULL DEFAULT 0,
    analyzed_pages            INTEGER NOT NULL DEFAULT 0,
    total_keywords            INTEGER NOT NULL DEFAULT 0,
    commercial_keyword_count  INTEGER NOT NULL DEFAULT 0,
    updated_at                TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- CORE: future-extension placeholders (schema only; see
-- competitive_intelligence/future/ for why no logic ships in P0)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ci_serp_queries (
    serp_query_id  TEXT PRIMARY KEY,
    domain_id      TEXT NOT NULL REFERENCES ci_domains(domain_id),
    keyword_id     TEXT REFERENCES ci_keywords(keyword_id),
    query_text     TEXT NOT NULL,
    provider       TEXT,
    requested_at   TEXT,
    status         TEXT NOT NULL DEFAULT 'not_implemented'
);
CREATE INDEX IF NOT EXISTS idx_ci_serp_queries_domain ON ci_serp_queries(domain_id);

CREATE TABLE IF NOT EXISTS ci_serp_results (
    serp_result_id  TEXT PRIMARY KEY,
    serp_query_id   TEXT NOT NULL REFERENCES ci_serp_queries(serp_query_id),
    rank_position   INTEGER,
    result_url      TEXT,
    result_domain   TEXT,
    fetched_at      TEXT
);
CREATE INDEX IF NOT EXISTS idx_ci_serp_results_query ON ci_serp_results(serp_query_id);

CREATE TABLE IF NOT EXISTS ci_opportunities (
    opportunity_id     TEXT PRIMARY KEY,
    domain_id          TEXT NOT NULL REFERENCES ci_domains(domain_id),
    keyword_id         TEXT REFERENCES ci_keywords(keyword_id),
    opportunity_score  REAL,
    recommendation     TEXT,
    status             TEXT NOT NULL DEFAULT 'not_implemented',
    created_at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ci_opportunities_domain ON ci_opportunities(domain_id);

CREATE TABLE IF NOT EXISTS ci_term_dictionary (
    term_id       TEXT PRIMARY KEY,
    term          TEXT NOT NULL UNIQUE,
    term_type     TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

-- ---------------------------------------------------------------------------
-- VERTICAL: genre-specific extension points (empty of business logic in P0)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ci_vertical_profiles (
    vertical_id  TEXT PRIMARY KEY,
    name         TEXT NOT NULL UNIQUE,
    description  TEXT,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ci_vertical_entities (
    vertical_entity_id  TEXT PRIMARY KEY,
    vertical_id         TEXT NOT NULL REFERENCES ci_vertical_profiles(vertical_id),
    name                TEXT NOT NULL,
    entity_type         TEXT,
    created_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ci_vertical_entities_vertical ON ci_vertical_entities(vertical_id);

CREATE TABLE IF NOT EXISTS ci_vertical_entity_attributes (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    vertical_entity_id  TEXT NOT NULL REFERENCES ci_vertical_entities(vertical_entity_id),
    attr_key            TEXT NOT NULL,
    attr_value          TEXT
);
CREATE INDEX IF NOT EXISTS idx_ci_vertical_entity_attrs_entity ON ci_vertical_entity_attributes(vertical_entity_id);

CREATE TABLE IF NOT EXISTS ci_external_source_mappings (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    vertical_entity_id  TEXT NOT NULL REFERENCES ci_vertical_entities(vertical_entity_id),
    external_source     TEXT NOT NULL,
    external_id         TEXT,
    UNIQUE(vertical_entity_id, external_source)
);

CREATE TABLE IF NOT EXISTS ci_vertical_keyword_metrics (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    vertical_id  TEXT NOT NULL REFERENCES ci_vertical_profiles(vertical_id),
    keyword_id   TEXT NOT NULL REFERENCES ci_keywords(keyword_id),
    metric_name  TEXT NOT NULL,
    metric_value REAL,
    UNIQUE(vertical_id, keyword_id, metric_name)
);
