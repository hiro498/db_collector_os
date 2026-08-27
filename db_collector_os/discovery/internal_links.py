"""Internal link discovery: given a page's extracted links, keep only same-
domain (or configured allowed-domain) links as new discovery candidates.

Optionally narrows further to links matching a job-supplied
`url_pattern` regex -- e.g. a product detail URL shape like
`/en/product/(\d+)/` -- so a job can grow its fetch queue from real,
page-embedded links without ever fetching (and wasting its `max_pages`
budget on) unrelated same-domain pages it already knows in advance won't
be entities (about/contact/cart/account/...). This filters *observed*
links; it never invents a URL the way discovery/url_pattern.py's ID-range
generator does.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from .base import DiscoveredURL


def discover_internal_links(
    links: list[str],
    base_domain: str,
    allowed_domains: set[str] | None = None,
    url_pattern: str | None = None,
) -> list[DiscoveredURL]:
    allowed = allowed_domains or {base_domain}
    compiled = re.compile(url_pattern) if url_pattern else None

    found = []
    for link in links:
        domain = urlsplit(link).netloc.lower()
        if domain not in allowed:
            continue

        stable_id = None
        if compiled is not None:
            match = compiled.search(link)
            if not match:
                continue
            if match.re.groups >= 1:
                stable_id = match.group(1)

        found.append(DiscoveredURL(url=link, method="internal_link", confidence=0.4, stable_id=stable_id))
    return found
