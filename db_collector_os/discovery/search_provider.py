"""Search-query discovery is Provider-based so a real search API (or none at
all) can be plugged in without touching the discovery engine. When no
provider is configured, NullSearchProvider makes the method a safe no-op --
the rest of the system keeps working.
"""

from __future__ import annotations

from typing import Protocol


class SearchProvider(Protocol):
    def search(self, query: str, max_results: int = 20) -> list[str]:
        """Return a list of result URLs for the query."""
        ...


class NullSearchProvider:
    """Used when no search provider is configured. Always returns nothing."""

    def search(self, query: str, max_results: int = 20) -> list[str]:
        return []


class StaticSearchProvider:
    """Test/offline provider: returns URLs from an in-memory mapping."""

    def __init__(self, fixtures: dict[str, list[str]]):
        self.fixtures = fixtures

    def search(self, query: str, max_results: int = 20) -> list[str]:
        return self.fixtures.get(query, [])[:max_results]


def build_search_provider(provider_name: str, api_key: str) -> SearchProvider:
    """Factory. Extend with real providers (e.g. Bing/Google CSE) as needed --
    unknown/blank provider names safely fall back to NullSearchProvider so a
    missing API key never stops the rest of discovery.
    """
    if not provider_name or not api_key:
        return NullSearchProvider()
    # Placeholder for real integrations. Unrecognized providers fail open.
    return NullSearchProvider()
