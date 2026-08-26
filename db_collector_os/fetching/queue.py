"""Fetch Queue: persistent, per-job URL queue. A failure on one URL or one
domain never stops the rest of the queue -- failed items are retried with
backoff up to max_attempts, then marked `failed` and left in place for
inspection instead of blocking anything else.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from ..database import Database
from ..job_registry import now_iso
from ..models.enums import QueueStatus
from .urlnorm import extract_domain, normalize_url


class FetchQueue:
    def __init__(self, db: Database):
        self.db = db

    def enqueue(self, job_id: str, url: str, priority: int = 50, max_attempts: int = 5) -> int | None:
        url = normalize_url(url)
        domain = extract_domain(url)
        existing = self.db.query_one(
            "SELECT queue_id, status FROM fetch_queue WHERE job_id=? AND url=?", (job_id, url)
        )
        if existing:
            return existing["queue_id"]
        cur = self.db.execute(
            """INSERT INTO fetch_queue (job_id, url, domain, priority, status, max_attempts, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (job_id, url, domain, priority, QueueStatus.QUEUED, max_attempts, now_iso()),
        )
        return cur.lastrowid

    def claim_next(self, job_id: str, ready_domains: set[str] | None = None) -> dict[str, Any] | None:
        """Atomically claim the highest-priority ready item for a job."""
        now = now_iso()
        with self.db.transaction() as conn:
            sql = (
                "SELECT * FROM fetch_queue WHERE job_id=? AND status=? "
                "AND (next_retry_at IS NULL OR next_retry_at <= ?)"
            )
            params: list[Any] = [job_id, QueueStatus.QUEUED, now]
            if ready_domains is not None:
                if not ready_domains:
                    return None
                placeholders = ",".join("?" for _ in ready_domains)
                sql += f" AND domain IN ({placeholders})"
                params.extend(ready_domains)
            sql += " ORDER BY priority DESC, queue_id LIMIT 1"
            row = conn.execute(sql, params).fetchone()
            if not row:
                return None
            conn.execute(
                "UPDATE fetch_queue SET status=? WHERE queue_id=?",
                (QueueStatus.FETCHING, row["queue_id"]),
            )
            row = dict(row)
            row["status"] = QueueStatus.FETCHING
            return row

    def mark_done(
        self,
        queue_id: int,
        http_status: int,
        content_hash: str | None = None,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> None:
        self.db.execute(
            """UPDATE fetch_queue SET status=?, last_http_status=?, fetched_at=?,
                 content_hash=?, etag=?, last_modified=?, error_message=NULL
               WHERE queue_id=?""",
            (QueueStatus.DONE, http_status, now_iso(), content_hash, etag, last_modified, queue_id),
        )

    def mark_skipped(self, queue_id: int, reason: str) -> None:
        self.db.execute(
            "UPDATE fetch_queue SET status=?, error_message=?, fetched_at=? WHERE queue_id=?",
            (QueueStatus.SKIPPED, reason, now_iso(), queue_id),
        )

    def mark_failed(
        self, queue_id: int, error_message: str, http_status: int | None = None, retry_after: float | None = None
    ) -> None:
        row = self.db.query_one("SELECT * FROM fetch_queue WHERE queue_id=?", (queue_id,))
        if not row:
            return
        attempts = row["attempt_count"] + 1
        if attempts >= row["max_attempts"]:
            self.db.execute(
                "UPDATE fetch_queue SET status=?, attempt_count=?, last_http_status=?, error_message=? WHERE queue_id=?",
                (QueueStatus.FAILED, attempts, http_status, error_message, queue_id),
            )
            return
        backoff = retry_after if retry_after is not None else min(2 ** attempts, 3600)
        next_retry = (datetime.now(timezone.utc) + timedelta(seconds=backoff)).isoformat(timespec="seconds")
        self.db.execute(
            """UPDATE fetch_queue SET status=?, attempt_count=?, last_http_status=?,
                 error_message=?, next_retry_at=? WHERE queue_id=?""",
            (QueueStatus.QUEUED, attempts, http_status, error_message, next_retry, queue_id),
        )

    def pending_count(self, job_id: str) -> int:
        row = self.db.query_one(
            "SELECT COUNT(*) AS n FROM fetch_queue WHERE job_id=? AND status=?",
            (job_id, QueueStatus.QUEUED),
        )
        return row["n"] if row else 0

    def stats(self, job_id: str) -> dict[str, int]:
        rows = self.db.query(
            "SELECT status, COUNT(*) AS n FROM fetch_queue WHERE job_id=? GROUP BY status", (job_id,)
        )
        return {r["status"]: r["n"] for r in rows}

    def is_empty(self, job_id: str) -> bool:
        return self.pending_count(job_id) == 0

    def requeue_stale_fetching(self, job_id: str) -> int:
        """Recover items stuck in 'fetching' because a worker died mid-fetch.
        Safe to call at the start of every run under the per-job-isolation
        invariant (one worker touches a given job's queue at a time).
        """
        cur = self.db.execute(
            "UPDATE fetch_queue SET status=? WHERE job_id=? AND status=?",
            (QueueStatus.QUEUED, job_id, QueueStatus.FETCHING),
        )
        return cur.rowcount

    def requeue_for_revalidation(self, job_id: str, older_than_seconds: float, limit: int = 500) -> int:
        """Incremental Update Engine: put previously-fetched items back in the
        queue for a conditional re-fetch (ETag/Last-Modified carried over),
        instead of re-crawling the whole DB from scratch every cycle.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=older_than_seconds)).isoformat(timespec="seconds")
        rows = self.db.query(
            """SELECT queue_id FROM fetch_queue WHERE job_id=? AND status=?
                 AND (fetched_at IS NULL OR fetched_at <= ?) LIMIT ?""",
            (job_id, QueueStatus.DONE, cutoff, limit),
        )
        ids = [r["queue_id"] for r in rows]
        for queue_id in ids:
            self.db.execute(
                "UPDATE fetch_queue SET status=?, attempt_count=0 WHERE queue_id=?",
                (QueueStatus.QUEUED, queue_id),
            )
        return len(ids)
