"""Keyword volume data-source adapters. Mirrors the
`discovery/search_provider.py` pattern already in this codebase: a small
Protocol, a safe no-op default, and a factory -- so a missing API
key/credential never breaks the rest of the pipeline, it just yields no
metrics for that source.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class KeywordMetricRecord:
    keyword: str
    monthly_search_volume: int | None
    source: str
    competition: float | None = None
    low_bid: float | None = None
    high_bid: float | None = None
    trend: str | None = None


class KeywordSource(Protocol):
    def fetch(self, keywords: list[str]) -> list[KeywordMetricRecord]:
        """Return whatever metrics are available for the given keywords.
        Keywords with no data available should simply be omitted from the
        result, not raise.
        """
        ...


class NullKeywordSource:
    """Used when a source isn't configured. Always returns nothing -- the
    rest of Phase 1 keeps working with whatever other sources/CSV imports
    already provided.
    """

    name = "null"

    def fetch(self, keywords: list[str]) -> list[KeywordMetricRecord]:
        return []


class NotConfiguredError(RuntimeError):
    """Raised by a real-API adapter's constructor when required credentials
    are missing, so the caller gets an explicit, actionable error instead of
    a confusing failure deep in an HTTP call.
    """
