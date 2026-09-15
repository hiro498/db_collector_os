from __future__ import annotations


def _seed_pages(db, count: int = 2) -> list[str]:
    from db_collector_os.competitive_intelligence.repository.core import (
        CrawlRunRepository, CrawlUrlRepository, DomainRepository,
    )
    from db_collector_os.competitive_intelligence.repository.pages import PageRepository

    domain = DomainRepository(db).get_or_create("example.jp", target_type="affiliate_domain")
    run_id = CrawlRunRepository(db).create(
        domain["domain_id"], "https://example.jp/", "affiliate_domain", "affiliate_domain", "general",
    )
    page_ids = []
    for i in range(count):
        crawl_url_id, _ = CrawlUrlRepository(db).add(
            run_id, domain["domain_id"], f"https://example.jp/{i}", f"https://example.jp/{i}", discovered_by="seed",
        )
        page_ids.append(PageRepository(db).upsert(
            crawl_url_id, run_id, domain["domain_id"], f"https://example.jp/{i}", f"https://example.jp/{i}",
            fetched_at="2026-01-01T00:00:00",
        ))
    return page_ids


def test_migration_0006_applied_and_prior_migrations_untouched(db):
    versions = {r["version"] for r in db.query("SELECT version FROM schema_migrations")}
    assert "0006_opportunity_analysis" in versions
    assert {
        "0001_init", "0002_competitive_intelligence", "0003_keyword_occurrence_span",
        "0004_ai_search_analysis", "0005_ai_search_observations",
    } <= versions


def test_migration_0006_creates_all_seven_tables(db):
    tables = {r["name"] for r in db.query("SELECT name FROM sqlite_master WHERE type='table'")}
    expected = {
        "ci_keyword_metrics", "ci_opportunity_analyses", "ci_opportunity_components",
        "ci_competitor_comparisons", "ci_content_gaps", "ci_opportunity_reasons", "ci_opportunity_actions",
    }
    assert expected <= tables


def test_opportunity_analyses_unique_constraint(db):
    import sqlite3

    import pytest

    (page_id,) = _seed_pages(db, 1)
    db.execute(
        "INSERT INTO ci_opportunity_analyses (opportunity_id, entity_type, entity_id, our_page_id, "
        "score_status, confidence_label, confidence_value, computed_at) "
        "VALUES ('o1','page',?,?,'COMPLETE','HIGH',0.9,'2026-01-01')",
        (page_id, page_id),
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO ci_opportunity_analyses (opportunity_id, entity_type, entity_id, our_page_id, "
            "score_status, confidence_label, confidence_value, computed_at) "
            "VALUES ('o2','page',?,?,'COMPLETE','HIGH',0.9,'2026-01-01')",
            (page_id, page_id),
        )


def test_keyword_metrics_unique_on_source_query_observed_at(db):
    import sqlite3

    import pytest

    db.execute(
        "INSERT INTO ci_keyword_metrics (keyword_metric_id, query, source, observed_at, created_at) "
        "VALUES ('m1','q','manual','2026-01-01','2026-01-01')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO ci_keyword_metrics (keyword_metric_id, query, source, observed_at, created_at) "
            "VALUES ('m2','q','manual','2026-01-01','2026-01-01')"
        )


def test_content_gaps_unique_on_our_page_and_competitor(db):
    import sqlite3

    import pytest

    p1, p2 = _seed_pages(db, 2)
    db.execute(
        "INSERT INTO ci_content_gaps (content_gap_id, our_page_id, competitor_page_id, content_gap_score, computed_at) "
        "VALUES ('g1',?,?,10.0,'2026-01-01')",
        (p1, p2),
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO ci_content_gaps (content_gap_id, our_page_id, competitor_page_id, content_gap_score, computed_at) "
            "VALUES ('g2',?,?,20.0,'2026-01-01')",
            (p1, p2),
        )


def test_competitor_comparisons_unique_on_pair_and_dimension(db):
    """comparisons are keyed loosely enough (left/right entity_type+id) that
    they need no FK -- entities can be pages, domains, or keywords."""
    import sqlite3

    import pytest

    db.execute(
        "INSERT INTO ci_competitor_comparisons (comparison_id, left_entity_type, left_entity_id, "
        "right_entity_type, right_entity_id, comparison_dimension, winner, confidence, computed_at) "
        "VALUES ('c1','page','p1','page','p2','organic_rank','left','HIGH','2026-01-01')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO ci_competitor_comparisons (comparison_id, left_entity_type, left_entity_id, "
            "right_entity_type, right_entity_id, comparison_dimension, winner, confidence, computed_at) "
            "VALUES ('c2','page','p1','page','p2','organic_rank','right','LOW','2026-01-01')"
        )


def test_ci_opportunity_analyses_is_a_separate_table_from_phase12_and_phase13(db):
    """Internal readiness (PHASE 12), external reality (PHASE 13), and
    Opportunity scoring (PHASE 14) must never be bolted onto one table."""
    analysis_columns = {r["name"] for r in db.query("PRAGMA table_info(ci_ai_page_analysis)")}
    visibility_columns = {r["name"] for r in db.query("PRAGMA table_info(ci_ai_page_visibility)")}
    opportunity_columns = {r["name"] for r in db.query("PRAGMA table_info(ci_opportunity_analyses)")}
    assert "overall_opportunity_score" not in analysis_columns
    assert "overall_opportunity_score" not in visibility_columns
    assert "overall_opportunity_score" in opportunity_columns
    assert "ai_citation_readiness_score" not in opportunity_columns


def test_integrity_check_ok_after_migration_0006(db):
    ok, detail = db.integrity_check()
    assert ok is True
    assert detail == "ok"
