"""Deduplicator: decides whether a new record is the same entity as an
existing one. Exact signals (fingerprint / canonical_url / external_id) merge
automatically. Anything only partially matching (e.g. same name, different
address) is never merged automatically -- it is routed to the review queue.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from ..entities import EntityStore
from .fingerprint import compute_fingerprint

Action = Literal["new", "merge", "review"]


@dataclass
class DedupDecision:
    action: Action
    entity_id: str | None = None
    reason: str | None = None
    fingerprint: str | None = None


class Deduplicator:
    def __init__(self, entities: EntityStore):
        self.entities = entities

    def resolve(
        self,
        job_id: str,
        entity_type: str,
        name: str | None = None,
        normalized_name: str | None = None,
        canonical_url: str | None = None,
        domain: str | None = None,
        address: str | None = None,
        telephone: str | None = None,
        external_id: str | None = None,
    ) -> DedupDecision:
        fingerprint = compute_fingerprint(
            entity_type, normalized_name=normalized_name, canonical_url=canonical_url,
            domain=domain, external_id=external_id,
        )

        if fingerprint:
            existing = self.entities.find_by_fingerprint(job_id, fingerprint)
            if existing:
                return DedupDecision("merge", existing["entity_id"], "fingerprint match", fingerprint)

        if canonical_url:
            existing = self.entities.find_by_canonical_url(job_id, canonical_url)
            if existing:
                return DedupDecision("merge", existing["entity_id"], "canonical_url match", fingerprint)

        # Fuzzy pass: same normalized name but signals disagree (different
        # domain/address/telephone) -> ambiguous, needs a human.
        if normalized_name:
            candidates = self._find_by_normalized_name(job_id, normalized_name)
            for cand in candidates:
                if self._conflicts(cand, domain, address, telephone):
                    return DedupDecision(
                        "review", cand["entity_id"],
                        "same name but conflicting domain/address/telephone", fingerprint,
                    )
            if candidates:
                # Same normalized name, no explicit conflict, but not enough to
                # auto-merge without at least one corroborating strong signal.
                return DedupDecision(
                    "review", candidates[0]["entity_id"],
                    "name matches but no strong corroborating signal", fingerprint,
                )

        return DedupDecision("new", None, "no match", fingerprint)

    def _find_by_normalized_name(self, job_id: str, normalized_name: str) -> list[dict[str, Any]]:
        rows = self.entities.db.query(
            "SELECT * FROM entities WHERE job_id=? AND normalized_name=? AND deleted_at IS NULL",
            (job_id, normalized_name),
        )
        from ..entities import _decode

        return [_decode(r) for r in rows]

    @staticmethod
    def _conflicts(existing: dict[str, Any], domain: str | None, address: str | None, telephone: str | None) -> bool:
        if domain and existing.get("domain") and existing["domain"] != domain:
            return True
        if address and existing.get("address") and existing["address"] != address:
            return True
        if telephone and existing.get("telephone") and existing["telephone"] != telephone:
            return True
        return False
