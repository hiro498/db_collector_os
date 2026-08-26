from __future__ import annotations

from db_collector_os.database import MIGRATIONS_DIR, apply_migrations, connect


def test_all_migration_files_are_applied(tmp_home):
    conn = connect(tmp_home / "m.sqlite3")
    applied = apply_migrations(conn)
    on_disk = {p.stem for p in MIGRATIONS_DIR.glob("*.sql")}
    assert set(applied) == on_disk
    conn.close()


def test_expected_tables_exist_after_migration(tmp_home):
    conn = connect(tmp_home / "m2.sqlite3")
    apply_migrations(conn)
    tables = {
        r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    expected = {
        "jobs", "entity_candidates", "fetch_queue", "domain_rate_limits", "entities",
        "evidence", "review_queue", "run_history", "discovery_runs", "daily_metrics",
        "checkpoints", "workers", "schema_migrations",
    }
    assert expected.issubset(tables)
    conn.close()


def test_schema_migrations_table_records_versions(tmp_home):
    conn = connect(tmp_home / "m3.sqlite3")
    apply_migrations(conn)
    rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    assert len(rows) >= 1
    conn.close()
