"""Sample api adapter: a generic JSON list/array API adapter (the shape used
by most product/catalog APIs -- FANZA/DUGA/MGS-style feeds included). Expects
a JSON payload that is either a top-level list of items, or an object with an
"items"/"results"/"data" list -- configurable per job via config_json.api.
"""

from __future__ import annotations

import json
from typing import Any

from .base import Adapter, ExtractedRecord
from .registry import register_adapter


@register_adapter("sample_api")
class SampleApiAdapter(Adapter):
    name = "sample_api"
    entity_type = "product"
    required_fields = ("name", "external_id")

    def __init__(self, items_path: str = "items", field_map: dict[str, str] | None = None):
        self.items_path = items_path
        self.field_map = field_map or {
            "name": "name", "id": "id", "url": "url",
        }

    def parse_api(self, payload: Any, url: str) -> list[ExtractedRecord]:
        if isinstance(payload, str):
            payload = json.loads(payload)

        items: list[Any]
        if isinstance(payload, list):
            items = payload
        elif isinstance(payload, dict):
            items = payload.get(self.items_path) or payload.get("results") or payload.get("data") or []
        else:
            items = []

        records = []
        fm = self.field_map
        for item in items:
            if not isinstance(item, dict):
                continue
            name = item.get(fm.get("name", "name"))
            ext_id = item.get(fm.get("id", "id"))
            item_url = item.get(fm.get("url", "url"))
            record = ExtractedRecord(
                name=str(name) if name is not None else None,
                entity_type=self.entity_type,
                canonical_url=item_url or url,
                external_id=str(ext_id) if ext_id is not None else None,
                confidence=0.8,
                fields={k: v for k, v in item.items() if k not in fm.values()},
            )
            missing = []
            if not record.name:
                missing.append("name")
            if not record.external_id:
                missing.append("external_id")
            record.missing_required = missing
            records.append(record)
        return records
