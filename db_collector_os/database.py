"""SQLite access layer: WAL mode, busy_timeout, migrations, integrity checks.

All writers (scheduler, worker, admin, CLI) open the same sqlite file. SQLite's
own locking plus a generous busy_timeout serializes concurrent writers safely;
within a single process, `Database.transaction()` additionally holds a
threading lock so multiple threads in one process never race on writes.
"""

from __future__ import annotations

import sqlite3
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator

BUSY_TIMEOUT_MS = 30_000
MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"

_write_lock = threading.RLock()


def new_id(prefix: str = "") -> str:
    token = uuid.uuid4().hex
    return f"{prefix}{token}" if prefix else token


def _row_factory(cursor: sqlite3.Cursor, row: tuple) -> dict[str, Any]:
    fields = [col[0] for col in cursor.description]
    return dict(zip(fields, row))


def connect(db_path: str | Path) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=BUSY_TIMEOUT_MS / 1000, check_same_thread=False)
    conn.row_factory = _row_factory
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def apply_migrations(conn: sqlite3.Connection, migrations_dir: Path | None = None) -> list[str]:
    """Apply any migration files not yet recorded in schema_migrations. Returns applied versions."""
    migrations_dir = migrations_dir or MIGRATIONS_DIR
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    applied = {row["version"] for row in conn.execute("SELECT version FROM schema_migrations")}

    newly_applied = []
    for path in sorted(migrations_dir.glob("*.sql")):
        version = path.stem
        if version in applied:
            continue
        sql = path.read_text(encoding="utf-8")
        with _write_lock:
            conn.executescript(sql)
            conn.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, datetime('now'))",
                (version,),
            )
            conn.commit()
        newly_applied.append(version)
    return newly_applied


def integrity_check(conn: sqlite3.Connection) -> tuple[bool, str]:
    row = conn.execute("PRAGMA integrity_check").fetchone()
    result = row["integrity_check"] if row else "unknown"
    return result == "ok", result


class Database:
    """Thin convenience wrapper around a sqlite3 connection for this app."""

    def __init__(self, db_path: str | Path, migrate: bool = True):
        self.db_path = Path(db_path)
        self.conn = connect(self.db_path)
        if migrate:
            apply_migrations(self.conn)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with _write_lock:
            try:
                yield self.conn
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise

    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self.transaction():
            return self.conn.execute(sql, params)

    def executemany(self, sql: str, seq_params: Iterable[Iterable[Any]]) -> sqlite3.Cursor:
        with self.transaction():
            return self.conn.executemany(sql, seq_params)

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        return list(self.conn.execute(sql, params).fetchall())

    def query_one(self, sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
        row = self.conn.execute(sql, params).fetchone()
        return row

    def integrity_check(self) -> tuple[bool, str]:
        return integrity_check(self.conn)
