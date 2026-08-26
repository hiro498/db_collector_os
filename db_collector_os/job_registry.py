"""Job Registry: CRUD + phase/status transitions for the `jobs` table."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from .database import Database, new_id
from .models.enums import JobPhase, JobStatus


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def now_plus(seconds: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat(timespec="seconds")


_SCHEDULE_RE = re.compile(r"^@every\s+(\d+)(s|m|h|d)$")
_NAMED_INTERVALS = {
    "@hourly": timedelta(hours=1),
    "@daily": timedelta(days=1),
    "@weekly": timedelta(weeks=1),
    "@minutely": timedelta(minutes=1),
}


def compute_next_run(schedule: str, base: datetime | None = None) -> str:
    """Very small schedule DSL: @hourly / @daily / @weekly / @minutely / @every <n><s|m|h|d>."""
    base = base or datetime.now(timezone.utc)
    schedule = (schedule or "@hourly").strip()

    if schedule in _NAMED_INTERVALS:
        delta = _NAMED_INTERVALS[schedule]
    else:
        m = _SCHEDULE_RE.match(schedule)
        if m:
            n, unit = int(m.group(1)), m.group(2)
            multiplier = {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
            delta = timedelta(seconds=n * multiplier)
        else:
            delta = timedelta(hours=1)
    return (base + delta).isoformat(timespec="seconds")


def row_to_job(row: dict[str, Any]) -> dict[str, Any]:
    row = dict(row)
    row["config_json"] = json.loads(row.get("config_json") or "{}")
    row["enabled"] = bool(row.get("enabled"))
    return row


class JobRegistry:
    def __init__(self, db: Database):
        self.db = db

    def create(
        self,
        job_name: str,
        category: str,
        target_db: str,
        target_table: str,
        collector_type: str,
        adapter: str,
        job_id: str | None = None,
        priority: int = 50,
        enabled: bool = True,
        schedule: str = "@hourly",
        max_pages: int = 200,
        max_depth: int = 3,
        concurrency: int = 2,
        rate_limit: float = 1.0,
        config: dict[str, Any] | None = None,
        phase: str = JobPhase.BOOTSTRAP,
    ) -> str:
        job_id = job_id or new_id("job_")
        ts = now_iso()
        self.db.execute(
            """INSERT INTO jobs (job_id, job_name, category, target_db, target_table,
                collector_type, adapter, priority, enabled, phase, schedule, max_pages,
                max_depth, concurrency, rate_limit, config_json, status, created_at,
                updated_at, next_run_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(job_id) DO UPDATE SET
                 job_name=excluded.job_name, category=excluded.category,
                 target_db=excluded.target_db, target_table=excluded.target_table,
                 collector_type=excluded.collector_type, adapter=excluded.adapter,
                 priority=excluded.priority, enabled=excluded.enabled,
                 schedule=excluded.schedule, max_pages=excluded.max_pages,
                 max_depth=excluded.max_depth, concurrency=excluded.concurrency,
                 rate_limit=excluded.rate_limit, config_json=excluded.config_json,
                 updated_at=excluded.updated_at
            """,
            (
                job_id, job_name, category, target_db, target_table, collector_type,
                adapter, priority, int(enabled), phase, schedule, max_pages, max_depth,
                concurrency, rate_limit, json.dumps(config or {}), JobStatus.IDLE, ts,
                ts, ts,  # next_run_at = now: a newly (re)synced job is eligible to run
                         # immediately rather than waiting a full schedule interval.
            ),
        )
        return job_id

    def get(self, job_id: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
        return row_to_job(row) if row else None

    def list(
        self, status: str | None = None, enabled_only: bool = False, category: str | None = None
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM jobs WHERE 1=1"
        params: list[Any] = []
        if status:
            sql += " AND status = ?"
            params.append(status)
        if enabled_only:
            sql += " AND enabled = 1"
        if category:
            sql += " AND category = ?"
            params.append(category)
        sql += " ORDER BY priority DESC, job_id"
        return [row_to_job(r) for r in self.db.query(sql, params)]

    def due_jobs(self, now: str | None = None) -> list[dict[str, Any]]:
        now = now or now_iso()
        rows = self.db.query(
            """SELECT * FROM jobs WHERE enabled = 1
                 AND status IN ('idle', 'completed', 'retry')
                 AND (next_run_at IS NULL OR next_run_at <= ?)
               ORDER BY priority DESC, next_run_at""",
            (now,),
        )
        return [row_to_job(r) for r in rows]

    def set_status(self, job_id: str, status: str) -> None:
        self.db.execute(
            "UPDATE jobs SET status = ?, updated_at = ? WHERE job_id = ?",
            (status, now_iso(), job_id),
        )

    def set_phase(self, job_id: str, phase: str) -> None:
        self.db.execute(
            "UPDATE jobs SET phase = ?, updated_at = ? WHERE job_id = ?",
            (phase, now_iso(), job_id),
        )

    def mark_queued(self, job_id: str) -> None:
        self.db.execute(
            "UPDATE jobs SET status = 'queued', updated_at = ? WHERE job_id = ? AND status IN ('idle','completed','retry')",
            (now_iso(), job_id),
        )

    def claim_queued(self, job_id: str) -> bool:
        """Atomically move a job from queued -> running. Returns True if claimed."""
        with self.db.transaction() as conn:
            cur = conn.execute(
                "UPDATE jobs SET status='running', last_started_at=?, updated_at=? "
                "WHERE job_id=? AND status='queued'",
                (now_iso(), now_iso(), job_id),
            )
            return cur.rowcount > 0

    def finish(
        self, job_id: str, status: str, next_phase: str | None = None, next_run_override: str | None = None
    ) -> None:
        job = self.get(job_id)
        schedule = job["schedule"] if job else "@hourly"
        if status == JobStatus.PAUSED:
            next_run = None
        elif next_run_override:
            next_run = next_run_override
        else:
            next_run = compute_next_run(schedule)
        sql = "UPDATE jobs SET status=?, last_finished_at=?, updated_at=?, next_run_at=?"
        params: list[Any] = [status, now_iso(), now_iso(), next_run]
        if next_phase:
            sql += ", phase=?"
            params.append(next_phase)
        sql += " WHERE job_id=?"
        params.append(job_id)
        self.db.execute(sql, params)

    def pause(self, job_id: str) -> None:
        self.set_status(job_id, JobStatus.PAUSED)

    def resume(self, job_id: str) -> None:
        self.db.execute(
            "UPDATE jobs SET status='idle', updated_at=?, next_run_at=? WHERE job_id=?",
            (now_iso(), now_iso(), job_id),
        )

    def set_enabled(self, job_id: str, enabled: bool) -> None:
        self.db.execute(
            "UPDATE jobs SET enabled=?, updated_at=? WHERE job_id=?",
            (int(enabled), now_iso(), job_id),
        )

    def reset_stale_running(self, job_id: str) -> None:
        """Used when a worker dies mid-job: put it back to retry so it can resume via checkpoint."""
        self.db.execute(
            "UPDATE jobs SET status='retry', updated_at=? WHERE job_id=? AND status='running'",
            (now_iso(), job_id),
        )
