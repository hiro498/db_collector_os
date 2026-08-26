"""Review Queue: anything the pipeline can't resolve automatically (ambiguous
duplicates, CAPTCHAs, parse failures, conflicting sources, low confidence,
etc.) lands here instead of silently corrupting the entities table.
"""

from __future__ import annotations

from typing import Any

from ..database import Database
from ..job_registry import now_iso
from ..models.enums import ReviewStatus


class ReviewQueue:
    def __init__(self, db: Database):
        self.db = db

    def add(
        self,
        job_id: str,
        reason: str,
        details: str | None = None,
        entity_id: str | None = None,
        candidate_id: str | None = None,
    ) -> int:
        cur = self.db.execute(
            """INSERT INTO review_queue (job_id, reason, details, entity_id, candidate_id, status, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (job_id, reason, details, entity_id, candidate_id, ReviewStatus.OPEN, now_iso()),
        )
        return cur.lastrowid

    def resolve(self, review_id: int) -> None:
        self.db.execute(
            "UPDATE review_queue SET status=?, resolved_at=? WHERE review_id=?",
            (ReviewStatus.RESOLVED, now_iso(), review_id),
        )

    def dismiss(self, review_id: int) -> None:
        self.db.execute(
            "UPDATE review_queue SET status=?, resolved_at=? WHERE review_id=?",
            (ReviewStatus.DISMISSED, now_iso(), review_id),
        )

    def list_open(self, job_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        if job_id:
            return self.db.query(
                "SELECT * FROM review_queue WHERE status='open' AND job_id=? ORDER BY created_at DESC LIMIT ?",
                (job_id, limit),
            )
        return self.db.query(
            "SELECT * FROM review_queue WHERE status='open' ORDER BY created_at DESC LIMIT ?", (limit,)
        )

    def count_open(self, job_id: str | None = None) -> int:
        if job_id:
            row = self.db.query_one(
                "SELECT COUNT(*) AS n FROM review_queue WHERE status='open' AND job_id=?", (job_id,)
            )
        else:
            row = self.db.query_one("SELECT COUNT(*) AS n FROM review_queue WHERE status='open'")
        return row["n"] if row else 0
