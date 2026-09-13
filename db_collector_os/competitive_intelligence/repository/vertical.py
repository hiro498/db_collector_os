"""Schema-only persistence for the VERTICAL bounded context (genre-specific
dictionaries/entities). CORE never imports genre-specific data; a concrete
vertical module (e.g. an "adult"/"vape"/... package, none of which ships in
this P0) would depend on this repository, never the other way around.
"""

from __future__ import annotations

from typing import Any

from ...database import Database, new_id
from ...job_registry import now_iso


class VerticalProfileRepository:
    def __init__(self, db: Database):
        self.db = db

    def get_or_create(self, name: str, description: str | None = None) -> dict[str, Any]:
        existing = self.db.query_one("SELECT * FROM ci_vertical_profiles WHERE name=?", (name,))
        if existing:
            return existing
        vertical_id = new_id("civert_")
        self.db.execute(
            "INSERT INTO ci_vertical_profiles (vertical_id, name, description, created_at) VALUES (?,?,?,?)",
            (vertical_id, name, description, now_iso()),
        )
        return self.db.query_one("SELECT * FROM ci_vertical_profiles WHERE vertical_id=?", (vertical_id,))

    def list(self) -> list[dict[str, Any]]:
        return self.db.query("SELECT * FROM ci_vertical_profiles ORDER BY name")


class VerticalEntityRepository:
    def __init__(self, db: Database):
        self.db = db

    def create(self, vertical_id: str, name: str, entity_type: str | None = None) -> str:
        vertical_entity_id = new_id("civent_")
        self.db.execute(
            "INSERT INTO ci_vertical_entities (vertical_entity_id, vertical_id, name, entity_type, created_at) "
            "VALUES (?,?,?,?,?)",
            (vertical_entity_id, vertical_id, name, entity_type, now_iso()),
        )
        return vertical_entity_id

    def set_attribute(self, vertical_entity_id: str, key: str, value: str) -> None:
        self.db.execute(
            "INSERT INTO ci_vertical_entity_attributes (vertical_entity_id, attr_key, attr_value) VALUES (?,?,?)",
            (vertical_entity_id, key, value),
        )

    def map_external_source(self, vertical_entity_id: str, external_source: str, external_id: str) -> None:
        self.db.execute(
            "INSERT OR IGNORE INTO ci_external_source_mappings "
            "(vertical_entity_id, external_source, external_id) VALUES (?,?,?)",
            (vertical_entity_id, external_source, external_id),
        )

    def list_for_vertical(self, vertical_id: str) -> list[dict[str, Any]]:
        return self.db.query("SELECT * FROM ci_vertical_entities WHERE vertical_id=?", (vertical_id,))
