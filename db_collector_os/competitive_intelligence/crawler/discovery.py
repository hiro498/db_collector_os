"""URL discovery for the affiliate_domain crawl mode (spec section 6):
sitemap / sitemap-index / internal-link / pagination. Reuses
discovery.sitemap/discovery.robots_sitemap as-is; the only new logic here
is classifying every link found on a page -- same-host candidates become
new crawl targets, everything else (subdomain, external domain, assets,
mailto/tel/javascript, admin paths) is still returned with its exclusion
reason rather than silently dropped (spec section 9: discovered URLs are
never simply discarded, even when out of crawl scope).
"""

from __future__ import annotations

from ...discovery.sitemap import discover_from_sitemap
from ...fetching.client import FetchEngine
from ..url_tools import classify_non_crawlable, is_pagination_url


def discover_sitemap_urls(fetch_engine: FetchEngine, root_url: str) -> list[dict]:
    """Tries robots.txt's declared sitemaps first, then the conventional
    `/sitemap.xml` path as a fallback -- spec section 6 says "must not stop
    at sitemap alone", but a sitemap is still the fastest legitimate source
    when present.
    """
    sitemap_urls = fetch_engine.robots.sitemaps(root_url) or [_default_sitemap_url(root_url)]
    found: list[dict] = []
    seen: set[str] = set()
    for sm_url in sitemap_urls:
        for discovered in discover_from_sitemap(fetch_engine, sm_url):
            if discovered.url in seen:
                continue
            seen.add(discovered.url)
            found.append({"url": discovered.url, "discovered_by": "sitemap"})
    return found


def discover_internal_links(page_url: str, links: list[str], base_host: str) -> list[dict]:
    """Classifies every link found on `page_url`. Each result is either
    `{"url", "discovered_by": "internal_link"|"pagination", "source_url"}`
    (a genuine new crawl candidate) or `{"url", "exclusion_reason",
    "source_url"}` (out of scope, but still worth recording -- see the
    module docstring).
    """
    found = []
    for link in links:
        exclusion = classify_non_crawlable(link, base_host)
        if exclusion is not None:
            found.append({"url": link, "exclusion_reason": exclusion, "source_url": page_url})
            continue
        discovered_by = "pagination" if is_pagination_url(link) else "internal_link"
        found.append({"url": link, "discovered_by": discovered_by, "source_url": page_url})
    return found


def _default_sitemap_url(root_url: str) -> str:
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(root_url)
    return urlunsplit((parts.scheme, parts.netloc, "/sitemap.xml", "", ""))
