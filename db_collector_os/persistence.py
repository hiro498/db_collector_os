"""Genre-agnostic persistence service for organized ExtractedRecord data.

One common path:

    ExtractedRecord
        -> validation
        -> normalization
        -> deduplication
        -> INSERT / UPDATE / REVIEW
        -> evidence

The service does not fetch URLs and does not depend on a site Adapter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .adapters.base import ExtractedRecord
from .deduplication import Deduplicator
from .entities import EntityStore, EvidenceStore
from .normalization import (
    normalize_address,
    normalize_name,
    normalize_telephone,
    normalize_url,
)
from .validation import validate_record


@dataclass
class PersistenceResult:
    action: str
    entity_id: str | None = None
    fingerprint: str | None = None
    reason: str | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class PersistenceService:
    """Common writer for already-organized records."""

    def __init__(
        self,
        entities: EntityStore,
        evidence: EvidenceStore,
        dedup: Deduplicator,
    ):
        self.entities = entities
        self.evidence = evidence
        self.dedup = dedup

    def persist(
        self,
        *,
        job_id: str,
        record: ExtractedRecord,
        source_url: str,
        domain: str | None = None,
        default_entity_type: str = "entity",
        required_fields: tuple[str, ...] | list[str] = (),
    ) -> PersistenceResult:

        if record.skip:
            return PersistenceResult(
                action="skip",
                reason=record.skip_reason or "record_marked_skip",
            )

        validation = validate_record(
            record,
            required_fields=required_fields,
        )

        if not validation.valid:
            return PersistenceResult(
                action="invalid",
                reason="validation_failed",
                errors=validation.errors,
                warnings=validation.warnings,
            )

        entity_type = record.entity_type or default_entity_type

        normalized_name = (
            normalize_name(record.name)
            if record.name
            else None
        )

        address = (
            normalize_address(record.address)
            if record.address
            else None
        )

        telephone = (
            normalize_telephone(record.telephone)
            if record.telephone
            else None
        )

        canonical_url = (
            normalize_url(record.canonical_url or source_url)
            if (record.canonical_url or source_url)
            else None
        )

        resolved_domain = (
            domain
            or record.domain
            or _domain_from_url(canonical_url)
            or _domain_from_url(source_url)
        )

        decision = self.dedup.resolve(
            job_id,
            entity_type,
            name=record.name,
            normalized_name=normalized_name,
            canonical_url=canonical_url,
            domain=resolved_domain,
            address=address,
            telephone=telephone,
            external_id=record.external_id,
        )

        if decision.action == "review":
            return PersistenceResult(
                action="review",
                entity_id=decision.entity_id,
                fingerprint=decision.fingerprint,
                reason=decision.reason,
                warnings=validation.warnings,
            )

        if decision.action == "new":
            entity_id = self.entities.create(
                job_id=job_id,
                entity_type=entity_type,
                name=record.name,
                normalized_name=normalized_name,
                canonical_url=canonical_url,
                domain=resolved_domain,
                address=address,
                telephone=telephone,
                external_id=record.external_id,
                fingerprint=decision.fingerprint,
                data=record.fields,
            )

            self._record_evidence(
                entity_id=entity_id,
                record=record,
                source_url=source_url,
            )

            return PersistenceResult(
                action="inserted",
                entity_id=entity_id,
                fingerprint=decision.fingerprint,
                reason=decision.reason,
                warnings=validation.warnings,
            )

        entity_id = decision.entity_id

        if not entity_id:
            return PersistenceResult(
                action="invalid",
                fingerprint=decision.fingerprint,
                reason="merge_without_entity_id",
                errors=["merge_without_entity_id"],
                warnings=validation.warnings,
            )

        self.entities.merge_data(
            entity_id,
            record.fields,
        )

        self._update_common_fields(
            entity_id=entity_id,
            record=record,
            normalized_name=normalized_name,
            canonical_url=canonical_url,
            domain=resolved_domain,
            address=address,
            telephone=telephone,
        )

        self._record_evidence(
            entity_id=entity_id,
            record=record,
            source_url=source_url,
        )

        return PersistenceResult(
            action="updated",
            entity_id=entity_id,
            fingerprint=decision.fingerprint,
            reason=decision.reason,
            warnings=validation.warnings,
        )

    def _update_common_fields(
        self,
        *,
        entity_id: str,
        record: ExtractedRecord,
        normalized_name: str | None,
        canonical_url: str | None,
        domain: str | None,
        address: str | None,
        telephone: str | None,
    ) -> None:
        current = self.entities.get(entity_id)

        if not current:
            return

        updates: dict[str, Any] = {}

        values = {
            "name": record.name,
            "normalized_name": normalized_name,
            "canonical_url": canonical_url,
            "domain": domain,
            "address": address,
            "telephone": telephone,
            "external_id": record.external_id,
        }

        # Never erase an existing useful value with None/blank.
        # A supplied non-empty organized value may refresh the current value.
        for field_name, value in values.items():
            if value is None:
                continue
            if isinstance(value, str) and not value.strip():
                continue
            if current.get(field_name) != value:
                updates[field_name] = value

        if updates:
            self.entities.update(entity_id, **updates)

    def _record_evidence(
        self,
        *,
        entity_id: str,
        record: ExtractedRecord,
        source_url: str,
    ) -> None:
        evidence_fields: dict[str, Any] = dict(record.fields)

        common_fields = {
            "name": record.name,
            "canonical_url": record.canonical_url,
            "address": record.address,
            "telephone": record.telephone,
            "external_id": record.external_id,
        }

        for key, value in common_fields.items():
            if value is not None:
                evidence_fields[key] = value

        self.evidence.record_many(
            entity_id,
            evidence_fields,
            source_url,
            record.confidence,
        )


def _domain_from_url(url: str | None) -> str | None:
    if not url:
        return None

    try:
        from urllib.parse import urlsplit

        host = urlsplit(url).netloc.lower().strip()

        if host.startswith("www."):
            host = host[4:]

        return host or None

    except Exception:
        return None
