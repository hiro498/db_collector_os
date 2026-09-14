"""Offline import of externally-gathered observation data (spec section
"Offline Import Requirement"). This is the *primary* way real observation
data enters this codebase: this environment's own network access to
general external sites is blocked (see this package's ``__init__.py``
docstring), so a JSON or CSV file gathered elsewhere -- a VPS-side probe, a
licensed SERP API export, a manual GSC export, a manual browser check -- is
imported here verbatim. Nothing here fabricates a field a source file
doesn't contain.

Two duplicate-protection layers apply:
1. The whole *file* is idempotent via its content hash + observation_type
   (``ImportBatchRepository`` / ``ci_observation_import_batches``):
   re-importing an unchanged file is always a safe no-op.
2. Each individual record still goes through its own repository's UNIQUE
   constraint, so a single file containing the same observation twice (or
   two separately-gathered files that happen to overlap) never double-counts.

Supported formats:
- JSON: a top-level list of *observation-level* records. For organic/AIO/
  AI Mode, each record already carries its nested ``results``/``citations``
  list (the natural shape for a hand-written or scripted export).
- CSV: one *flat* row per result/citation (or, for fanout/GSC, one row per
  observation -- those are already flat). Rows that share the same
  query/country/language/device/observed_at/provider are grouped back into
  one observation before being handed to the same repositories JSON uses.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ....database import Database
from .enums import ObservationType
from .repository import (
    AioObservationRepository,
    AiModeObservationRepository,
    FanoutObservationRepository,
    GscObservationRepository,
    ImportBatchRepository,
    SerpObservationRepository,
)
from .url_matching import normalize_citation_url

_OBS_KEY_FIELDS = ("query", "country", "language", "device", "observed_at", "provider")
_SCALAR_PASSTHROUGH_FIELDS = (
    "keyword_id", "status", "response_hash", "raw_reference", "aio_present", "aio_text_hash",
)
_NESTED_ITEM_FIELDS = {
    "results": ("result_position", "result_url", "normalized_url", "result_domain", "title", "snippet",
                "result_type"),
    "citations": ("citation_position", "citation_url", "normalized_url", "citation_domain",
                  "citation_anchor_text", "citation_context", "citation_source_type"),
}


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _domain_of(url: str) -> str:
    return urlparse(url).netloc


def _coerce_int(value: Any) -> int | None:
    return None if value in (None, "") else int(value)


def _coerce_float(value: Any) -> float | None:
    return None if value in (None, "") else float(value)


def _coerce_bool(value: Any) -> bool | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes")


def _load_records(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError("JSON import file must contain a top-level list of records")
        return data
    if suffix == ".csv":
        with path.open(newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    raise ValueError(f"unsupported import file type: {suffix} (expected .json or .csv)")


def _group_flat_rows(rows: list[dict[str, Any]], nested_key: str, item_fields: tuple[str, ...]) -> list[dict[str, Any]]:
    """Reassembles CSV's flat one-row-per-result/citation shape back into
    the same observation-level shape a JSON file already carries."""
    groups: dict[tuple, dict[str, Any]] = {}
    order: list[tuple] = []
    for row in rows:
        key = tuple(row.get(f) for f in _OBS_KEY_FIELDS)
        if key not in groups:
            record = {f: row.get(f) for f in _OBS_KEY_FIELDS}
            record.update({f: row.get(f) for f in _SCALAR_PASSTHROUGH_FIELDS if row.get(f) not in (None, "")})
            record[nested_key] = []
            groups[key] = record
            order.append(key)
        item = {f: row.get(f) for f in item_fields if row.get(f) not in (None, "")}
        if item:
            groups[key][nested_key].append(item)
    return [groups[k] for k in order]


def _normalize_result(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "result_position": _coerce_int(item["result_position"]),
        "result_url": item["result_url"],
        "normalized_url": item.get("normalized_url") or normalize_citation_url(item["result_url"]),
        "result_domain": item.get("result_domain") or _domain_of(item["result_url"]),
        "title": item.get("title"),
        "snippet": item.get("snippet"),
        "result_type": item.get("result_type") or "organic",
    }


def _normalize_citation(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "citation_position": _coerce_int(item.get("citation_position")),
        "citation_url": item["citation_url"],
        "normalized_url": item.get("normalized_url") or normalize_citation_url(item["citation_url"]),
        "citation_domain": item.get("citation_domain") or _domain_of(item["citation_url"]),
        "citation_anchor_text": item.get("citation_anchor_text"),
        "citation_context": item.get("citation_context"),
        "citation_source_type": item.get("citation_source_type"),
    }


def _import_organic(db: Database, records: list[dict[str, Any]]) -> tuple[int, int, int]:
    repo = SerpObservationRepository(db)
    imported = skipped = errors = 0
    for row in records:
        try:
            obs_id = repo.record(
                query=row["query"], country=row.get("country") or "JP", language=row.get("language") or "ja",
                device=row.get("device") or "desktop", observed_at=row["observed_at"], provider=row["provider"],
                status=row.get("status") or "available", keyword_id=row.get("keyword_id"),
                response_hash=row.get("response_hash"), raw_reference=row.get("raw_reference"),
                results=[_normalize_result(r) for r in row.get("results", [])],
            )
            if obs_id:
                imported += 1
            else:
                skipped += 1
        except Exception:
            errors += 1
    return imported, skipped, errors


def _import_aio_like(
    db: Database, records: list[dict[str, Any]], repo: AioObservationRepository | AiModeObservationRepository,
    supports_aio_present: bool,
) -> tuple[int, int, int]:
    imported = skipped = errors = 0
    for row in records:
        try:
            citations = [_normalize_citation(c) for c in row.get("citations", [])]
            kwargs: dict[str, Any] = dict(
                query=row["query"], country=row.get("country") or "JP", language=row.get("language") or "ja",
                device=row.get("device") or "desktop", observed_at=row["observed_at"], provider=row["provider"],
                status=row.get("status") or "available", keyword_id=row.get("keyword_id"),
                response_hash=row.get("response_hash"), raw_reference=row.get("raw_reference"),
                citations=citations,
            )
            if supports_aio_present:
                kwargs["aio_present"] = _coerce_bool(row.get("aio_present"))
                kwargs["aio_text_hash"] = row.get("aio_text_hash")
            obs_id = repo.record(**kwargs)
            if obs_id:
                imported += 1
            else:
                skipped += 1
        except Exception:
            errors += 1
    return imported, skipped, errors


def _resolve_fanout_query_id(db: Database, row: dict[str, Any]) -> str | None:
    if row.get("fanout_query_id"):
        return row["fanout_query_id"]
    if row.get("target_page_id") and row.get("fanout_query"):
        match = db.query_one(
            "SELECT fanout_query_id FROM ci_ai_fanout_queries WHERE page_id=? AND subquery_text=?",
            (row["target_page_id"], row["fanout_query"]),
        )
        if match:
            return match["fanout_query_id"]
    return None


def _parse_result_urls(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return value
    text = str(value).strip()
    if text.startswith("["):
        return json.loads(text)
    return [u.strip() for u in text.split("|") if u.strip()]


def _import_fanout(db: Database, records: list[dict[str, Any]]) -> tuple[int, int, int]:
    """No per-record UNIQUE constraint exists on ci_fanout_observations --
    a single fan-out subquery is legitimately re-observed many times over
    time, unlike organic/AIO/AI-Mode which key on one row per
    (query, ..., observed_at, provider). File-level idempotency
    (``ImportBatchRepository``) is this data's duplicate protection."""
    repo = FanoutObservationRepository(db)
    imported = skipped = errors = 0
    for row in records:
        try:
            fanout_query_id = _resolve_fanout_query_id(db, row)
            if not fanout_query_id:
                errors += 1
                continue
            repo.record(
                fanout_query_id=fanout_query_id, parent_query=row["parent_query"],
                fanout_query=row["fanout_query"], fanout_intent=row.get("fanout_intent") or "informational",
                country=row.get("country") or "JP", language=row.get("language") or "ja",
                device=row.get("device") or "desktop", observed_at=row["observed_at"], provider=row["provider"],
                status=row.get("status") or "available", target_page_id=row.get("target_page_id"),
                target_rank=_coerce_int(row.get("target_rank")), target_cited=_coerce_bool(row.get("target_cited")),
                result_urls=_parse_result_urls(row.get("result_urls")),
                response_hash=row.get("response_hash"), raw_reference=row.get("raw_reference"),
            )
            imported += 1
        except Exception:
            errors += 1
    return imported, skipped, errors


def _import_gsc(db: Database, records: list[dict[str, Any]]) -> tuple[int, int, int]:
    repo = GscObservationRepository(db)
    imported = skipped = errors = 0
    for row in records:
        try:
            normalized_page = row.get("normalized_page") or normalize_citation_url(row["gsc_page"])
            obs_id = repo.record(
                gsc_query=row["gsc_query"], gsc_page=row["gsc_page"], normalized_page=normalized_page,
                observed_date=row["observed_date"], country=row.get("country") or None,
                device=row.get("device") or None, data_source_category=row.get("data_source_category") or "search",
                impressions=_coerce_int(row.get("impressions")), clicks=_coerce_int(row.get("clicks")),
                ctr=_coerce_float(row.get("ctr")), position=_coerce_float(row.get("position")),
            )
            if obs_id:
                imported += 1
            else:
                skipped += 1
        except Exception:
            errors += 1
    return imported, skipped, errors


def import_observation_file(
    db: Database, file_path: str, observation_type: str, provider: str | None = None,
) -> dict[str, Any]:
    if observation_type not in ObservationType.ALL:
        raise ValueError(f"unknown observation_type: {observation_type!r}")

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(file_path)
    file_hash = _file_hash(path)

    existing = db.query_one(
        "SELECT * FROM ci_observation_import_batches WHERE file_hash=? AND observation_type=?",
        (file_hash, observation_type),
    )
    if existing:
        return {"status": "already_imported", "batch": existing}

    raw_records = _load_records(path)
    is_csv = path.suffix.lower() == ".csv"

    if observation_type == ObservationType.ORGANIC:
        records = _group_flat_rows(raw_records, "results", _NESTED_ITEM_FIELDS["results"]) if is_csv else raw_records
        imported, skipped, errors = _import_organic(db, records)
    elif observation_type == ObservationType.AIO:
        records = (
            _group_flat_rows(raw_records, "citations", _NESTED_ITEM_FIELDS["citations"]) if is_csv else raw_records
        )
        imported, skipped, errors = _import_aio_like(db, records, AioObservationRepository(db), supports_aio_present=True)
    elif observation_type == ObservationType.AI_MODE:
        records = (
            _group_flat_rows(raw_records, "citations", _NESTED_ITEM_FIELDS["citations"]) if is_csv else raw_records
        )
        imported, skipped, errors = _import_aio_like(
            db, records, AiModeObservationRepository(db), supports_aio_present=False
        )
    elif observation_type == ObservationType.FANOUT:
        imported, skipped, errors = _import_fanout(db, raw_records)
    else:  # GSC
        imported, skipped, errors = _import_gsc(db, raw_records)

    batch_id = ImportBatchRepository(db).record(
        file_path=str(path), file_hash=file_hash, observation_type=observation_type, provider=provider,
        imported_count=imported, skipped_duplicate_count=skipped, error_count=errors,
    )
    return {
        "status": "imported", "batch_id": batch_id, "imported": imported,
        "skipped_duplicate": skipped, "errors": errors,
    }
