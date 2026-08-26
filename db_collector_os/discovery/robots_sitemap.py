"""robots.txt `Sitemap:` directive discovery."""

from __future__ import annotations

from ..fetching.client import FetchEngine
from .base import DiscoveredURL
from .sitemap import discover_from_sitemap


def discover_from_robots(fetch_engine: FetchEngine, seed_url: str, max_urls: int = 5000) -> list[DiscoveredURL]:
    sitemap_urls = fetch_engine.robots.sitemaps(seed_url)
    found: list[DiscoveredURL] = []
    for sm_url in sitemap_urls:
        found.extend(discover_from_sitemap(fetch_engine, sm_url, max_urls - len(found)))
        if len(found) >= max_urls:
            break
    return found[:max_urls]
