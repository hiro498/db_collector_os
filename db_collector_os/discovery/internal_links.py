"""Internal link discovery: given a page's extracted links, keep only same-
domain (or configured allowed-domain) links as new discovery candidates.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from .base import DiscoveredURL


def discover_internal_links(
    links: list[str], base_domain: str, allowed_domains: set[str] | None = None
) -> list[DiscoveredURL]:
    allowed = allowed_domains or {base_domain}
    found = []
    for link in links:
        domain = urlsplit(link).netloc.lower()
        if domain in allowed:
            found.append(DiscoveredURL(url=link, method="internal_link", confidence=0.4))
    return found
