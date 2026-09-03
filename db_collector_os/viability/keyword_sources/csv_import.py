"""CSV import keyword source: the functional, always-available path for
Phase 1. Accepts a manually exported CSV (e.g. from Google Keyword Planner's
own CSV export, or from ラッコキーワード's export, or hand-typed) with at
least `keyword` and `monthly_search_volume` columns.

Expected columns (header row required, extra columns ignored):
    keyword                  (required)
    monthly_search_volume    (required; blank/non-numeric -> None)
    competition               (optional, 0-1 float or blank)
    low_bid                   (optional, float or blank)
    high_bid                  (optional, float or blank)
    trend                     (optional, free text, e.g. "up"/"down"/"flat")
    source                    (optional; defaults to the `default_source` ctor arg)
"""

from __future__ import annotations

import csv
from pathlib import Path

from .base import KeywordMetricRecord


def _to_int(value: str | None) -> int | None:
    if value is None or value.strip() == "":
        return None
    try:
        return int(float(value.replace(",", "")))
    except ValueError:
        return None


def _to_float(value: str | None) -> float | None:
    if value is None or value.strip() == "":
        return None
    try:
        return float(value.replace(",", ""))
    except ValueError:
        return None


class CsvKeywordSource:
    def __init__(self, csv_path: str | Path, default_source: str = "csv_import"):
        self.csv_path = Path(csv_path)
        self.default_source = default_source

    def fetch(self, keywords: list[str] | None = None) -> list[KeywordMetricRecord]:
        """`keywords`, if given, filters the CSV to just those rows -- pass
        None to load every row in the file.
        """
        wanted = set(keywords) if keywords is not None else None
        records: list[KeywordMetricRecord] = []
        with open(self.csv_path, encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                keyword = (row.get("keyword") or "").strip()
                if not keyword or (wanted is not None and keyword not in wanted):
                    continue
                records.append(
                    KeywordMetricRecord(
                        keyword=keyword,
                        monthly_search_volume=_to_int(row.get("monthly_search_volume")),
                        source=(row.get("source") or "").strip() or self.default_source,
                        competition=_to_float(row.get("competition")),
                        low_bid=_to_float(row.get("low_bid")),
                        high_bid=_to_float(row.get("high_bid")),
                        trend=(row.get("trend") or "").strip() or None,
                    )
                )
        return records
