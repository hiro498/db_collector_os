from __future__ import annotations


def test_migration_0004_applied(db):
    versions = {r["version"] for r in db.query("SELECT version FROM schema_migrations")}
    assert "0004_ai_search_analysis" in versions
    # existing baseline migrations must remain untouched/still applied
    assert {"0001_init", "0002_competitive_intelligence", "0003_keyword_occurrence_span"} <= versions


def test_migration_0004_creates_all_six_tables(db):
    tables = {r["name"] for r in db.query("SELECT name FROM sqlite_master WHERE type='table'")}
    expected = {
        "ci_ai_page_analysis", "ci_ai_numeric_facts", "ci_ai_comparisons",
        "ci_ai_fanout_queries", "ci_ai_citation_observations", "ci_ai_freshness_events",
    }
    assert expected <= tables


def test_ci_ai_page_analysis_has_expected_null_capable_columns(db):
    columns = {r["name"] for r in db.query("PRAGMA table_info(ci_ai_page_analysis)")}
    for col in ("organic_visibility_score", "aio_citation_score", "ai_mode_citation_score",
                "fanout_coverage_score", "source_affinity_score", "ai_search_total_score",
                "ai_citation_readiness_score"):
        assert col in columns


def test_ci_ai_fanout_queries_unique_constraint(db):
    from db_collector_os.competitive_intelligence.repository.core import (
        CrawlRunRepository, CrawlUrlRepository, DomainRepository,
    )
    from db_collector_os.competitive_intelligence.repository.pages import PageRepository
    from db_collector_os.competitive_intelligence.ai_search.repository import AiFanoutQueryRepository

    domain = DomainRepository(db).get_or_create("example.jp", target_type="affiliate_domain")
    run_id = CrawlRunRepository(db).create(domain["domain_id"], "https://example.jp/", "affiliate_domain",
                                            "affiliate_domain", "general")
    crawl_url_id, _ = CrawlUrlRepository(db).add(run_id, domain["domain_id"], "https://example.jp/a",
                                                  "https://example.jp/a", discovered_by="seed")
    page_id = PageRepository(db).upsert(crawl_url_id, run_id, domain["domain_id"], "https://example.jp/a",
                                         "https://example.jp/a", fetched_at="2024-01-01T00:00:00")

    # UNIQUE(page_id, subquery_text): two candidates with the same
    # subquery_text for the same page must not both be insertable.
    repo = AiFanoutQueryRepository(db)
    import sqlite3
    import pytest
    with pytest.raises(sqlite3.IntegrityError):
        repo.replace_for_page(page_id, [
            {"base_keyword": "kw", "subquery_text": "kwとは", "intent_class": "informational",
             "covered_by_content": False},
            {"base_keyword": "kw", "subquery_text": "kwとは", "intent_class": "informational",
             "covered_by_content": False},
        ])


def test_integrity_check_ok_after_migration(db):
    ok, detail = db.integrity_check()
    assert ok is True
    assert detail == "ok"
