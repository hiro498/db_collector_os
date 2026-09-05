"""Common validation for normalized ExtractedRecord objects.

This module is deliberately genre-agnostic.

Adapters remain responsible for extraction and for declaring which fields
are required for their entity type.  This validator provides the common
gate immediately before deduplication/persistence.

It does not write to the database.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from .adapters.base import ExtractedRecord


@dataclass
class ValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def validate_record(
    record: ExtractedRecord,
    required_fields: tuple[str, ...] | list[str] = (),
) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []

    if record.skip:
        return ValidationResult(
            valid=False,
            errors=["record_marked_skip"],
        )

    required = list(dict.fromkeys([
        *required_fields,
        *record.missing_required,
    ]))

    for field_name in required:
        value = _get_value(record, field_name)
        if _is_missing(value):
            errors.append(f"missing_required:{field_name}")

    if not _is_missing(record.name):
        if not isinstance(record.name, str):
            errors.append("invalid_type:name")
        elif not record.name.strip():
            errors.append("empty:name")

    if not _is_missing(record.entity_type):
        if not isinstance(record.entity_type, str):
            errors.append("invalid_type:entity_type")
        elif not record.entity_type.strip():
            errors.append("empty:entity_type")

    if record.fields is None:
        errors.append("invalid_type:fields")
    elif not isinstance(record.fields, dict):
        errors.append("invalid_type:fields")

    if not isinstance(record.confidence, (int, float)) or isinstance(record.confidence, bool):
        errors.append("invalid_type:confidence")
    elif not 0.0 <= float(record.confidence) <= 1.0:
        errors.append("invalid_range:confidence")

    for field_name in ("canonical_url",):
        value = getattr(record, field_name, None)
        if _is_missing(value):
            continue
        if not isinstance(value, str):
            errors.append(f"invalid_type:{field_name}")
            continue
        if not _valid_http_url(value):
            errors.append(f"invalid_url:{field_name}")

    for field_name in ("domain", "address", "telephone", "external_id"):
        value = getattr(record, field_name, None)
        if _is_missing(value):
            continue
        if not isinstance(value, str):
            errors.append(f"invalid_type:{field_name}")

    if isinstance(record.fields, dict):
        for key in record.fields:
            if not isinstance(key, str) or not key.strip():
                errors.append("invalid_fields_key")
                break

        _validate_json_value(record.fields, "fields", errors)

    if record.canonical_url and not record.domain:
        warnings.append("domain_missing_but_derivable")

    return ValidationResult(
        valid=not errors,
        errors=_unique(errors),
        warnings=_unique(warnings),
    )


def _get_value(record: ExtractedRecord, field_name: str) -> Any:
    if hasattr(record, field_name):
        return getattr(record, field_name)

    fields = record.fields if isinstance(record.fields, dict) else {}
    return fields.get(field_name)


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def _valid_http_url(value: str) -> bool:
    try:
        parsed = urlsplit(value.strip())
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except Exception:
        return False


def _validate_json_value(value: Any, path: str, errors: list[str]) -> None:
    if value is None or isinstance(value, (str, int, float, bool)):
        return

    if isinstance(value, list):
        for idx, item in enumerate(value):
            _validate_json_value(item, f"{path}[{idx}]", errors)
        return

    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                errors.append(f"non_json_key:{path}")
                continue
            _validate_json_value(item, f"{path}.{key}", errors)
        return

    errors.append(f"non_json_value:{path}")


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
