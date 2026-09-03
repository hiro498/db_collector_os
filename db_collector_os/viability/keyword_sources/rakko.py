"""ラッコキーワード (Rakko Keyword) adapter -- placeholder.

Rakko Keyword has no official public data API; its site's own terms only
support interactive/manual use (and a paid plan for bulk related-keyword
export). Scraping it programmatically would be exactly the kind of
unauthorized bulk collection this project's rules forbid. The supported
path is: export candidates/volumes manually from the Rakko Keyword UI (CSV
or copy/paste into a CSV) and load them with keyword_sources.csv_import,
tagging `source=rakko` in that CSV (or via `default_source="rakko"`).

This module exists as a named, discoverable stub so a future *officially
licensed* Rakko data feed (if one is ever offered) has an obvious place to
be wired in without touching the rest of Phase 1.
"""

from __future__ import annotations

from .base import KeywordMetricRecord, NotConfiguredError


class RakkoKeywordSource:
    name = "rakko"

    def __init__(self):
        raise NotConfiguredError(
            "No official Rakko Keyword API is available. Export data from the Rakko Keyword "
            "UI as CSV and load it with keyword_sources.csv_import.CsvKeywordSource "
            "(default_source='rakko')."
        )

    def fetch(self, keywords: list[str]) -> list[KeywordMetricRecord]:  # pragma: no cover - unreachable
        raise NotImplementedError
