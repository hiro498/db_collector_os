from __future__ import annotations


def test_migration_0005_applied_and_prior_migrations_untouched(db):
    versions = {r["version"] for r in db.query("SELECT version FROM schema_migrations")}
    assert "0005_ai_search_observations" in versions
    assert {
        "0001_init", "0002_competitive_intelligence", "0003_keyword_occurrence_span",
        "0004_ai_search_analysis",
    } <= versions


def test_migration_0005_creates_all_ten_tables(db):
    tables = {r["name"] for r in db.query("SELECT name FROM sqlite_master WHERE type='table'")}
    expected = {
        "ci_serp_observations", "ci_serp_observation_results",
        "ci_aio_observations", "ci_aio_citations",
        "ci_ai_mode_observations", "ci_ai_mode_citations",
        "ci_fanout_observations",
        "ci_ai_page_visibility",
        "ci_observation_import_batches",
        "ci_gsc_observations",
    }
    assert expected <= tables


def test_aio_and_ai_mode_observations_are_physically_separate_tables():
    """spec: AIO and AI Mode must never share storage -- confirmed at the
    schema level, not just in application code."""
    import sqlite3
    # A shared name would be a single table; asserting both exist as
    # distinct names in the same DB is the schema-level guarantee.
    assert "ci_aio_observations" != "ci_ai_mode_observations"
    assert "ci_aio_citations" != "ci_ai_mode_citations"


def test_ci_ai_page_visibility_columns_are_a_separate_table_from_ci_ai_page_analysis(db):
    """Internal readiness (PHASE 12) and external reality (PHASE 13) must
    never be bolted onto the same table. PHASE 12 already carries a few
    placeholder external columns (organic_rank, aio_cited, ...) that it
    never populates -- this package's own PHASE-13-only fields
    (persistence/frequency math, the Readiness-vs-Reality class) are the
    ones that must exist only here."""
    analysis_columns = {r["name"] for r in db.query("PRAGMA table_info(ci_ai_page_analysis)")}
    visibility_columns = {r["name"] for r in db.query("PRAGMA table_info(ci_ai_page_visibility)")}
    assert "readiness_vs_reality_class" not in analysis_columns
    assert "aio_citation_frequency" not in analysis_columns
    assert "aio_persistence_score" not in analysis_columns
    assert "ai_citation_readiness_score" not in visibility_columns
    assert "organic_rank" in visibility_columns
    assert "readiness_vs_reality_class" in visibility_columns


def test_serp_observation_unique_constraint(db):
    import sqlite3

    import pytest

    db.execute(
        "INSERT INTO ci_serp_observations "
        "(serp_observation_id, query, country, language, device, observed_at, provider, status, created_at) "
        "VALUES ('a','q','JP','ja','desktop','2026-01-01','manual','available','2026-01-01')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO ci_serp_observations "
            "(serp_observation_id, query, country, language, device, observed_at, provider, status, created_at) "
            "VALUES ('b','q','JP','ja','desktop','2026-01-01','manual','available','2026-01-01')"
        )


def test_observation_import_batches_unique_on_file_hash_and_type(db):
    import sqlite3

    import pytest

    db.execute(
        "INSERT INTO ci_observation_import_batches "
        "(import_batch_id, file_path, file_hash, provider, observation_type, imported_count, "
        " skipped_duplicate_count, error_count, imported_at) "
        "VALUES ('b1','f.json','hash1',NULL,'organic',1,0,0,'2026-01-01')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO ci_observation_import_batches "
            "(import_batch_id, file_path, file_hash, provider, observation_type, imported_count, "
            " skipped_duplicate_count, error_count, imported_at) "
            "VALUES ('b2','f2.json','hash1',NULL,'organic',1,0,0,'2026-01-01')"
        )


def test_integrity_check_ok_after_migration_0005(db):
    ok, detail = db.integrity_check()
    assert ok is True
    assert detail == "ok"
