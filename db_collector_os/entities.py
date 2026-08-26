"""Entity store + Evidence (provenance) writer.

Every field written to `entities.data_json` should have a matching row in
`evidence` recording which URL it came from, when, and with what confidence --
this is the traceability the whole system is built around.
"""

from __future__ import annotations

import json
from typing import Any

from .database import Database, new_id
from .job_registry import now_iso


class EntityStore:
    def __init__(self, db: Database):
        self.db = db

    def find_by_fingerprint(self, job_id: str, fingerprint: str) -> dict[str, Any] | None:
        row = self.db.query_one(
            "SELECT * FROM entities WHERE job_id=? AND fingerprint=? AND deleted_at IS NULL",
            (job_id, fingerprint),
        )
        return _decode(row) if row else None

    def find_by_canonical_url(self, job_id: str, canonical_url: str) -> dict[str, Any] | None:
        row = self.db.query_one(
            "SELECT * FROM entities WHERE job_id=? AND canonical_url=? AND deleted_at IS NULL",
            (job_id, canonical_url),
        )
        return _decode(row) if row else None

    def get(self, entity_id: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM entities WHERE entity_id=?", (entity_id,))
        return _decode(row) if row else None

    def create(
        self,
        job_id: str,
        entity_type: str,
        name: str | None,
        normalized_name: str | None,
        canonical_url: str | None,
        domain: str | None,
        address: str | None,
        telephone: str | None,
        external_id: str | None,
        fingerprint: str | None,
        data: dict[str, Any],
    ) -> str:
        entity_id = new_id("ent_")
        ts = now_iso()
        self.db.execute(
            """INSERT INTO entities (entity_id, job_id, entity_type, name, normalized_name,
                 canonical_url, domain, address, telephone, external_id, fingerprint,
                 data_json, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                entity_id, job_id, entity_type, name, normalized_name, canonical_url,
                domain, address, telephone, external_id, fingerprint, json.dumps(data), ts, ts,
            ),
        )
        return entity_id

    def update(self, entity_id: str, **fields: Any) -> None:
        if not fields:
            return
        if "data" in fields:
            fields["data_json"] = json.dumps(fields.pop("data"))
        fields["updated_at"] = now_iso()
        set_clause = ", ".join(f"{k}=?" for k in fields)
        self.db.execute(
            f"UPDATE entities SET {set_clause} WHERE entity_id=?",
            (*fields.values(), entity_id),
        )

    def merge_data(self, entity_id: str, new_data: dict[str, Any]) -> None:
        entity = self.get(entity_id)
        if not entity:
            return
        merged = dict(entity.get("data", {}))
        merged.update(new_data)
        self.update(entity_id, data=merged)

    def count(self, job_id: str) -> int:
        row = self.db.query_one(
            "SELECT COUNT(*) AS n FROM entities WHERE job_id=? AND deleted_at IS NULL", (job_id,)
        )
        return row["n"] if row else 0

    def list(self, job_id: str, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM entities WHERE job_id=? AND deleted_at IS NULL ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            (job_id, limit, offset),
        )
        return [_decode(r) for r in rows]


def _decode(row: dict[str, Any]) -> dict[str, Any]:
    row = dict(row)
    row["data"] = json.loads(row.pop("data_json") or "{}")
    return row


class EvidenceStore:
    def __init__(self, db: Database):
        self.db = db

    def record(
        self, entity_id: str, field: str, value: Any, source_url: str, confidence: float = 0.5,
        fetched_at: str | None = None,
    ) -> int:
        cur = self.db.execute(
            """INSERT INTO evidence (entity_id, field, value, source_url, fetched_at, confidence)
               VALUES (?,?,?,?,?,?)""",
            (
                entity_id, field, json.dumps(value) if not isinstance(value, str) else value,
                source_url, fetched_at or now_iso(), confidence,
            ),
        )
        return cur.lastrowid

    def record_many(self, entity_id: str, fields: dict[str, Any], source_url: str, confidence: float = 0.5) -> None:
        ts = now_iso()
        for field, value in fields.items():
            self.record(entity_id, field, value, source_url, confidence, ts)

    def for_entity(self, entity_id: str) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM evidence WHERE entity_id=? ORDER BY fetched_at DESC", (entity_id,)
        )

    def for_field(self, entity_id: str, field: str) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM evidence WHERE entity_id=? AND field=? ORDER BY fetched_at DESC",
            (entity_id, field),
        )
