"""Sample person adapter: generic schema.org Person adapter. Applies to any
public-figure directory (fortune tellers, wrestlers, idols, K-pop members,
cosplayers, ...) that publishes Person structured data or a predictable
profile page layout -- nothing site-specific.
"""

from __future__ import annotations

from typing import Any

from .base import Adapter, ExtractedRecord
from .registry import register_adapter


@register_adapter("sample_person")
class SamplePersonAdapter(Adapter):
    name = "sample_person"
    entity_type = "person"
    required_fields = ("name",)

    def extract(self, common: dict[str, Any], url: str, raw_html: str | None) -> ExtractedRecord:
        person_block = next((b for b in common.get("json_ld", []) if "Person" in _types(b)), None)

        name = (person_block or {}).get("name") or common.get("name") or common.get("title")
        job_title = (person_block or {}).get("jobTitle") if person_block else None
        affiliation = (person_block or {}).get("affiliation") if person_block else None
        if isinstance(affiliation, dict):
            affiliation = affiliation.get("name")
        same_as = (person_block or {}).get("sameAs") or common.get("social_urls", [])
        if isinstance(same_as, str):
            same_as = [same_as]

        record = ExtractedRecord(
            name=name,
            entity_type=self.entity_type,
            canonical_url=common.get("canonical_url") or url,
            confidence=0.75 if person_block else 0.5,
            fields={
                "job_title": job_title,
                "affiliation": affiliation,
                "social_urls": same_as,
                "image_urls": common.get("image_urls", [])[:3],
            },
        )
        if not record.name:
            record.missing_required = ["name"]
        return record


def _types(block: dict[str, Any]) -> list[str]:
    t = block.get("@type")
    if isinstance(t, list):
        return t
    return [t] if t else []
