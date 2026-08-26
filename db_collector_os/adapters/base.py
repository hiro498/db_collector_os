"""Adapter interface. A new DB is added by writing one Adapter (+ a Job
definition) -- the core pipeline never needs to change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExtractedRecord:
    """What an Adapter hands back to the collector pipeline for one fetched page."""

    name: str | None = None
    entity_type: str | None = None
    canonical_url: str | None = None
    domain: str | None = None
    address: str | None = None
    telephone: str | None = None
    external_id: str | None = None
    confidence: float = 0.6
    fields: dict[str, Any] = field(default_factory=dict)  # everything else, DB-specific
    missing_required: list[str] = field(default_factory=list)


class Adapter:
    """Base class every DB-specific adapter extends.

    Subclasses typically only need to override `extract` (and optionally
    `seed_urls` / `required_fields`); the common extractor
    (extraction.common.extract_common) already fills in title/canonical/meta/
    JSON-LD/name/address/telephone/links/images for them.
    """

    name: str = "base"
    entity_type: str = "entity"
    required_fields: tuple[str, ...] = ("name",)

    def seed_urls(self, job: dict[str, Any]) -> list[str]:
        """Initial URLs to enqueue at bootstrap. Default: from job config_json.seed_urls."""
        cfg = job.get("config_json", {}) or {}
        return list(cfg.get("seed_urls", []))

    def extract(self, common: dict[str, Any], url: str, raw_html: str | None) -> ExtractedRecord:
        """Build an ExtractedRecord from the commonly-extracted fields. Override
        to pull DB-specific fields out of `common['json_ld']` or `raw_html`.
        """
        record = ExtractedRecord(
            name=common.get("name"),
            entity_type=self.entity_type,
            canonical_url=common.get("canonical_url") or url,
            address=common.get("address"),
            telephone=common.get("telephone"),
            confidence=0.6,
            fields={
                "title": common.get("title"),
                "meta_description": common.get("meta_description"),
                "social_urls": common.get("social_urls"),
                "image_urls": common.get("image_urls")[:5] if common.get("image_urls") else [],
            },
        )
        record.missing_required = [f for f in self.required_fields if not getattr(record, f, None) and f not in record.fields]
        return record

    def parse_api(self, payload: Any, url: str) -> list[ExtractedRecord]:
        """For collector_type == 'api': parse a decoded JSON payload into zero
        or more ExtractedRecords (one API response page can list many
        entities). Override in API adapters; the base raises so a missing
        override fails loudly rather than silently producing nothing.
        """
        raise NotImplementedError(f"{type(self).__name__} must implement parse_api()")
