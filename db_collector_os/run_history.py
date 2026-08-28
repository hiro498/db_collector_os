"""Run History: one row per job execution, plus discovery-run stats used for
saturation detection."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .database import Database, new_id
from .job_registry import now_iso
from .models.enums import RunStatus


class RunHistoryStore:
    def __init__(self, db: Database):
        self.db = db

    def start(self, job_id: str) -> str:
        run_id = new_id("run_")
        self.db.execute(
            "INSERT INTO run_history (run_id, job_id, started_at, status) VALUES (?,?,?,?)",
            (run_id, job_id, now_iso(), RunStatus.RUNNING),
        )
        return run_id

    def get(self, run_id: str) -> dict[str, Any] | None:
        return self.db.query_one("SELECT * FROM run_history WHERE run_id=?", (run_id,))

    def finish(self, run_id: str, status: str, **counts: int) -> bool:
        """Finalize a run. run_history is immutable execution history: a row
        that has already been finalized (status != running, or missing
        entirely) is never re-finalized -- returns False and leaves it
        untouched instead of silently overwriting its finished_at/counts.
        Returns True if this call actually finalized the row.
        """
        row = self.db.query_one("SELECT started_at, status FROM run_history WHERE run_id=?", (run_id,))
        if not row or row["status"] != RunStatus.RUNNING:
            return False
        duration = None
        if row["started_at"]:
            try:
                started = datetime.fromisoformat(row["started_at"])
                duration = (datetime.now(started.tzinfo) - started).total_seconds()
            except ValueError:
                duration = None
        fields = {
            "status": status,
            "finished_at": now_iso(),
            "duration_seconds": duration,
        }
        for key in (
            "discovered_count", "fetched_count", "inserted_count", "updated_count",
            "duplicate_count", "review_count", "error_count",
        ):
            if key in counts:
                fields[key] = counts[key]
        set_clause = ", ".join(f"{k}=?" for k in fields)
        self.db.execute(
            f"UPDATE run_history SET {set_clause} WHERE run_id=? AND status=?",
            (*fields.values(), run_id, RunStatus.RUNNING),
        )
        return True

    def for_job(self, job_id: str, limit: int = 20) -> list[dict[str, Any]]:
        # started_at has only second-level precision (see now_iso()), so two
        # runs created within the same second -- entirely possible for a
        # fast job or a rapid retry -- would tie on it alone. `rowid` (every
        # ordinary SQLite table has one; run_history's PK is TEXT, not
        # INTEGER, so it isn't aliased to rowid) breaks the tie in actual
        # insertion order, so "most recent" is never ambiguous.
        return self.db.query(
            "SELECT * FROM run_history WHERE job_id=? ORDER BY started_at DESC, rowid DESC LIMIT ?",
            (job_id, limit),
        )

    def record_discovery_stats(
        self, job_id: str, run_id: str, discovered_total: int, new_candidates: int,
        duplicate_candidates: int, accepted: int, rejected: int,
    ) -> None:
        self.db.execute(
            """INSERT INTO discovery_runs (job_id, run_id, discovered_total, new_candidates,
                 duplicate_candidates, accepted, rejected, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (job_id, run_id, discovered_total, new_candidates, duplicate_candidates, accepted, rejected, now_iso()),
        )

    def recent_discovery_runs(self, job_id: str, n: int = 5) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM discovery_runs WHERE job_id=? ORDER BY created_at DESC LIMIT ?",
            (job_id, n),
        )
