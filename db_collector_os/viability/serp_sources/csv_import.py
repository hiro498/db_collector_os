"""CSV import SERP source: the functional, always-available path for Phase
2. Accepts a manually collected/exported CSV of search results (e.g. from a
SERP API's own CSV export, or hand-recorded top-10 results).

Expected columns (header row required, extra columns ignored):
    query               (required)
    rank                (required, integer)
    title               (optional)
    url                 (optional)
    domain              (optional; derived from url if blank)
    snippet             (optional)
    site_type           (optional manual override -- see competition_analysis.SITE_TYPES)
    page_type           (optional manual override -- listing|product|article)
    title_match         (optional manual override -- exact|partial|none)
    db_type_page        (optional manual override -- true/false/1/0)
    intent_satisfied    (optional manual override -- true/false/1/0)
    source              (optional; defaults to the `default_source` ctor arg)
"""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlsplit

from .base import NotConfiguredError, SerpQueryResult, SerpResultRecord

__all__ = ["CsvSerpSource", "NotConfiguredError"]


def _to_bool(value: str | None) -> bool | None:
    if value is None or value.strip() == "":
        return None
    return value.strip().lower() in ("1", "true", "yes", "y")


def _domain_of(url: str | None) -> str | None:
    if not url:
        return None
    try:
        return urlsplit(url).netloc or None
    except ValueError:
        return None


class CsvSerpSource:
    def __init__(self, csv_path: str | Path, default_source: str = "csv_import"):
        self.csv_path = Path(csv_path)
        self.default_source = default_source
        self._by_query: dict[str, list[SerpResultRecord]] = defaultdict(list)
        self._source_by_query: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        with open(self.csv_path, encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                query = (row.get("query") or "").strip()
                rank_raw = (row.get("rank") or "").strip()
                if not query or not rank_raw:
                    continue
                url = (row.get("url") or "").strip() or None
                record = SerpResultRecord(
                    rank=int(float(rank_raw)),
                    title=(row.get("title") or "").strip() or None,
                    url=url,
                    domain=(row.get("domain") or "").strip() or _domain_of(url),
                    snippet=(row.get("snippet") or "").strip() or None,
                    site_type=(row.get("site_type") or "").strip() or None,
                    page_type=(row.get("page_type") or "").strip() or None,
                    title_match=(row.get("title_match") or "").strip() or None,
                    db_type_page=_to_bool(row.get("db_type_page")),
                    intent_satisfied=_to_bool(row.get("intent_satisfied")),
                )
                self._by_query[query].append(record)
                self._source_by_query[query] = (row.get("source") or "").strip() or self.default_source

        for results in self._by_query.values():
            results.sort(key=lambda r: r.rank)

    def search(self, query: str, max_results: int = 10) -> SerpQueryResult:
        results = self._by_query.get(query, [])[:max_results]
        return SerpQueryResult(query=query, source=self._source_by_query.get(query, self.default_source), results=results)

    def queries(self) -> list[str]:
        return list(self._by_query.keys())
