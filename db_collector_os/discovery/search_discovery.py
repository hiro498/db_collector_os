"""Search-query based discovery. Uses whatever SearchProvider is configured;
with NullSearchProvider (the default when no API key is set) this simply
returns no results without raising, so the rest of the system is unaffected.
"""

from __future__ import annotations

from .base import DiscoveredURL
from .search_provider import SearchProvider


def discover_from_search(provider: SearchProvider, queries: list[str], max_results_per_query: int = 20) -> list[DiscoveredURL]:
    found: list[DiscoveredURL] = []
    for query in queries:
        try:
            urls = provider.search(query, max_results=max_results_per_query)
        except Exception:
            continue  # a provider outage must never stop the rest of discovery
        found.extend(DiscoveredURL(url=u, method="search_query", confidence=0.5) for u in urls)
    return found
