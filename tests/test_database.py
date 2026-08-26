from __future__ import annotations

from db_collector_os.database import Database, apply_migrations, connect, new_id


def test_new_id_prefix():
    assert new_id("job_").startswith("job_")
    assert new_id() != new_id()


def test_wal_and_pragmas(tmp_home):
    db = Database(tmp_home / "wal.sqlite3")
    mode = db.conn.execute("PRAGMA journal_mode").fetchone()["journal_mode"]
    assert mode == "wal"
    fk = db.conn.execute("PRAGMA foreign_keys").fetchone()["foreign_keys"]
    assert fk == 1
    db.close()


def test_migrations_are_idempotent(tmp_home):
    conn = connect(tmp_home / "mig.sqlite3")
    applied_first = apply_migrations(conn)
    assert "0001_init" in applied_first
    applied_second = apply_migrations(conn)
    assert applied_second == []  # nothing new to apply
    conn.close()


def test_integrity_check(db):
    ok, result = db.integrity_check()
    assert ok
    assert result == "ok"


def test_transaction_rollback_on_error(db):
    db.execute("INSERT INTO jobs (job_id, job_name, category, target_db, target_table, collector_type, "
               "adapter, status, created_at, updated_at) VALUES ('j1','n','c','d','t','official_site','a','idle','x','x')")
    try:
        with db.transaction() as conn:
            conn.execute("UPDATE jobs SET job_name='changed' WHERE job_id='j1'")
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    row = db.query_one("SELECT job_name FROM jobs WHERE job_id='j1'")
    assert row["job_name"] == "n"  # rolled back
