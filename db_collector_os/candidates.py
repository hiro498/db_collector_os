"""Entity Candidate store: discovery results land here first, never directly
into the `entities` table. Also tracks per-run discovery statistics used for
saturation detection (see discovery/saturation.py).
"""

from __future__ import annotations

from typing import Any

from .database import Database, new_id
from .job_registry import now_iso
from .models.enums import CandidateStatus


class CandidateStore:
    def __init__(self, db: Database):
        self.db = db

    def add(
        self,
        job_id: str,
        entity_type: str,
        name: str | None,
        normalized_name: str | None,
        url: str | None,
        source_url: str | None,
        discovery_method: str,
        fingerprint: str | None,
        confidence: float = 0.5,
    ) -> tuple[str, bool]:
        """Insert a new candidate unless one with the same (job_id, fingerprint)
        already exists. Returns (candidate_id, created)."""
        if fingerprint:
            existing = self.db.query_one(
                "SELECT candidate_id FROM entity_candidates WHERE job_id=? AND fingerprint=?",
                (job_id, fingerprint),
            )
            if existing:
                return existing["candidate_id"], False

        candidate_id = new_id("cand_")
        self.db.execute(
            """INSERT INTO entity_candidates
               (candidate_id, job_id, entity_type, name, normalized_name, url,
                source_url, discovery_method, fingerprint, confidence, status, discovered_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                candidate_id, job_id, entity_type, name, normalized_name, url,
                source_url, discovery_method, fingerprint, confidence,
                CandidateStatus.NEW, now_iso(),
            ),
        )
        return candidate_id, True

    def set_status(self, candidate_id: str, status: str) -> None:
        self.db.execute(
            "UPDATE entity_candidates SET status=?, reviewed_at=? WHERE candidate_id=?",
            (status, now_iso(), candidate_id),
        )

    def list_new(self, job_id: str, limit: int = 500) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM entity_candidates WHERE job_id=? AND status='new' ORDER BY confidence DESC LIMIT ?",
            (job_id, limit),
        )

    def counts_by_status(self, job_id: str) -> dict[str, int]:
        rows = self.db.query(
            "SELECT status, COUNT(*) AS n FROM entity_candidates WHERE job_id=? GROUP BY status",
            (job_id,),
        )
        return {r["status"]: r["n"] for r in rows}

    def get(self, candidate_id: str) -> dict[str, Any] | None:
        return self.db.query_one(
            "SELECT * FROM entity_candidates WHERE candidate_id=?", (candidate_id,)
        )

    def get_by_url(self, job_id: str, url: str) -> dict[str, Any] | None:
        return self.db.query_one(
            "SELECT * FROM entity_candidates WHERE job_id=? AND url=? ORDER BY discovered_at DESC LIMIT 1",
            (job_id, url),
        )

    def total_count(self, job_id: str) -> int:
        row = self.db.query_one("SELECT COUNT(*) AS n FROM entity_candidates WHERE job_id=?", (job_id,))
        return row["n"] if row else 0
