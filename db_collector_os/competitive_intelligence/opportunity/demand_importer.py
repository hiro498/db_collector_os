"""Offline import of keyword demand metrics (spec section 16). Live
connections to Google Ads API / Rakko Keyword / Semrush etc. are explicitly
out of scope for PHASE 14 -- this is the only way real search_volume/
trend/cpc data enters `ci_keyword_metrics`, and it never fabricates a
volume for a query that isn't in the imported file.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from ...database import Database
from .repository import KeywordMetricsRepository


def _coerce_int(value: Any) -> int | None:
    return None if value in (None, "") else int(value)


def _coerce_float(value: Any) -> float | None:
    return None if value in (None, "") else float(value)


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


def import_keyword_metrics_file(db: Database, file_path: str) -> dict[str, Any]:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(file_path)

    records = _load_records(path)
    repo = KeywordMetricsRepository(db)
    imported = skipped = errors = 0
    for row in records:
        try:
            metric_id = repo.record(
                query=row["query"], source=row["source"], observed_at=row["observed_at"],
                search_volume=_coerce_int(row.get("search_volume")), impressions=_coerce_int(row.get("impressions")),
                clicks=_coerce_int(row.get("clicks")), ctr=_coerce_float(row.get("ctr")),
                trend=row.get("trend") or None, seasonality=row.get("seasonality") or None,
                related_query_count=_coerce_int(row.get("related_query_count")), cpc=_coerce_float(row.get("cpc")),
                competition=_coerce_float(row.get("competition")),
            )
            if metric_id:
                imported += 1
            else:
                skipped += 1
        except Exception:
            errors += 1
    return {"imported": imported, "skipped_duplicate": skipped, "errors": errors}
