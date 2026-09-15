from __future__ import annotations


def test_migration_0007_applied_and_prior_migrations_untouched(db):
    versions = {r["version"] for r in db.query("SELECT version FROM schema_migrations")}
    assert "0007_production_validation" in versions
    assert {
        "0001_init", "0002_competitive_intelligence", "0003_keyword_occurrence_span",
        "0004_ai_search_analysis", "0005_ai_search_observations", "0006_opportunity_analysis",
    } <= versions


def test_migration_0007_creates_all_three_tables(db):
    tables = {r["name"] for r in db.query("SELECT name FROM sqlite_master WHERE type='table'")}
    expected = {"ci_validation_runs", "ci_domain_keyword_summary", "ci_target_keyword_priorities"}
    assert expected <= tables


def test_ci_site_profiles_not_duplicated(db):
    """spec section 28: don't duplicate responsibility with the existing
    coarse per-domain ci_site_profiles table."""
    tables = {r["name"] for r in db.query("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "ci_site_profiles" in tables
    summary_columns = {r["name"] for r in db.query("PRAGMA table_info(ci_domain_keyword_summary)")}
    assert "total_pages" not in summary_columns  # that stays ci_site_profiles's job


def test_domain_keyword_summary_unique_constraint(db):
    import sqlite3

    import pytest

    db.execute(
        "INSERT INTO ci_validation_runs (validation_run_id, target_url, status, started_at) "
        "VALUES ('v1','https://example.jp/','RUNNING','2026-01-01')"
    )
    db.execute(
        "INSERT INTO ci_domain_keyword_summary (summary_id, validation_run_id, keyword, normalized_keyword, "
        "computed_at) VALUES ('s1','v1','kw','kw','2026-01-01')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO ci_domain_keyword_summary (summary_id, validation_run_id, keyword, normalized_keyword, "
            "computed_at) VALUES ('s2','v1','kw','kw','2026-01-01')"
        )


def test_target_keyword_priorities_unique_constraint(db):
    import sqlite3

    import pytest

    db.execute(
        "INSERT INTO ci_validation_runs (validation_run_id, target_url, status, started_at) "
        "VALUES ('v1','https://example.jp/','RUNNING','2026-01-01')"
    )
    db.execute(
        "INSERT INTO ci_target_keyword_priorities (priority_id, validation_run_id, priority_rank, keyword, "
        "normalized_keyword, computed_at) VALUES ('p1','v1',1,'kw','kw','2026-01-01')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO ci_target_keyword_priorities (priority_id, validation_run_id, priority_rank, keyword, "
            "normalized_keyword, computed_at) VALUES ('p2','v1',2,'kw','kw','2026-01-01')"
        )


def test_integrity_check_ok_after_migration_0007(db):
    ok, detail = db.integrity_check()
    assert ok is True
    assert detail == "ok"
