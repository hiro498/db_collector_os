"""URL pattern discovery: expands numeric page/ID ranges in a URL template,
e.g. "https://example.com/item/{id}" for id in a given range. Useful for
catalog-style sites with predictable IDs (product DBs, listing pages, ...).
"""

from __future__ import annotations

from .base import DiscoveredURL


def discover_by_url_pattern(
    url_template: str, start: int, end: int, step: int = 1, placeholder: str = "{n}"
) -> list[DiscoveredURL]:
    if placeholder not in url_template:
        return []
    found = []
    for n in range(start, end + 1, step):
        found.append(
            DiscoveredURL(url=url_template.replace(placeholder, str(n)), method="url_pattern", confidence=0.4)
        )
    return found
