"""Related-entity discovery: follow `sameAs` / adapter-declared related-link
fields found in already-extracted structured data, so the crawl grows
outward from confirmed entities instead of only from the seed list.
"""

from __future__ import annotations

from typing import Any

from .base import DiscoveredURL


def discover_related_entities(json_ld_blocks: list[dict[str, Any]]) -> list[DiscoveredURL]:
    found = []
    for block in json_ld_blocks:
        same_as = block.get("sameAs")
        if isinstance(same_as, str):
            same_as = [same_as]
        for url in same_as or []:
            if isinstance(url, str) and url.startswith("http"):
                found.append(DiscoveredURL(url=url, method="related_entity", confidence=0.45))
    return found
