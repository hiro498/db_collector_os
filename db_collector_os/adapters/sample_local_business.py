"""Sample local_business adapter: generic schema.org LocalBusiness adapter.
Applies to any storefront/venue category (fortune-telling parlors, live
houses, love hotels, dance schools, theaters, ...) that publishes
LocalBusiness / structured address+phone data -- nothing site-specific.
"""

from __future__ import annotations

from typing import Any

from .base import Adapter, ExtractedRecord
from .registry import register_adapter


@register_adapter("sample_local_business")
class SampleLocalBusinessAdapter(Adapter):
    name = "sample_local_business"
    entity_type = "local_business"
    required_fields = ("name", "address")

    def extract(self, common: dict[str, Any], url: str, raw_html: str | None) -> ExtractedRecord:
        biz_block = next(
            (b for b in common.get("json_ld", []) if "LocalBusiness" in _types(b) or "Organization" in _types(b)),
            None,
        )

        name = (biz_block or {}).get("name") or common.get("name") or common.get("title")
        address = common.get("address")
        telephone = (biz_block or {}).get("telephone") or common.get("telephone")
        opening_hours = (biz_block or {}).get("openingHours") if biz_block else None
        geo = (biz_block or {}).get("geo") if biz_block else None

        record = ExtractedRecord(
            name=name,
            entity_type=self.entity_type,
            canonical_url=common.get("canonical_url") or url,
            address=address,
            telephone=telephone,
            confidence=0.75 if biz_block else 0.5,
            fields={
                "opening_hours": opening_hours,
                "geo": geo,
                "social_urls": common.get("social_urls", []),
            },
        )
        missing = []
        if not record.name:
            missing.append("name")
        if not record.address:
            missing.append("address")
        record.missing_required = missing
        return record


def _types(block: dict[str, Any]) -> list[str]:
    t = block.get("@type")
    if isinstance(t, list):
        return t
    return [t] if t else []
