"""SERP (search-result) data-source adapters -- same adapter pattern as
keyword_sources: a Protocol, a safe no-op default, real integrations fail
closed with a clear error until credentials exist.

None of these ever perform bulk/unauthorized scraping of Google directly --
see serp_api.py's docstring and the module-level note in
db_collector_os/viability/__init__.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class SerpResultRecord:
    rank: int
    title: str | None = None
    url: str | None = None
    domain: str | None = None
    snippet: str | None = None
    # Optional manual/heuristic classification -- see competition_analysis.py.
    site_type: str | None = None
    page_type: str | None = None
    title_match: str | None = None  # "exact" | "partial" | "none"
    db_type_page: bool | None = None
    intent_satisfied: bool | None = None


@dataclass
class SerpQueryResult:
    query: str
    source: str
    results: list[SerpResultRecord] = field(default_factory=list)


class SerpSource(Protocol):
    def search(self, query: str, max_results: int = 10) -> SerpQueryResult:
        ...


class NullSerpSource:
    name = "null"

    def search(self, query: str, max_results: int = 10) -> SerpQueryResult:
        return SerpQueryResult(query=query, source=self.name, results=[])


class NotConfiguredError(RuntimeError):
    """Raised by a real SERP adapter's constructor when required
    credentials are missing."""
