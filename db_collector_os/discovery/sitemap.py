"""sitemap.xml discovery, including nested sitemap indexes."""

from __future__ import annotations

from xml.etree import ElementTree

from ..fetching.client import FetchEngine
from .base import DiscoveredURL

_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def discover_from_sitemap(
    fetch_engine: FetchEngine, sitemap_url: str, max_urls: int = 5000, _depth: int = 0
) -> list[DiscoveredURL]:
    if _depth > 3:
        return []
    result = fetch_engine.fetch(sitemap_url)
    if not result.ok or not result.content:
        return []

    try:
        root = ElementTree.fromstring(result.content.encode("utf-8", errors="ignore"))
    except ElementTree.ParseError:
        return []

    tag = root.tag.lower()
    found: list[DiscoveredURL] = []

    if tag.endswith("sitemapindex"):
        for sm in root.findall("sm:sitemap", _NS) or root.findall("sitemap"):
            loc = sm.findtext("sm:loc", namespaces=_NS) or sm.findtext("loc")
            if loc:
                found.extend(
                    discover_from_sitemap(fetch_engine, loc.strip(), max_urls - len(found), _depth + 1)
                )
            if len(found) >= max_urls:
                break
        return found[:max_urls]

    for url_el in root.findall("sm:url", _NS) or root.findall("url"):
        loc = url_el.findtext("sm:loc", namespaces=_NS) or url_el.findtext("loc")
        lastmod = url_el.findtext("sm:lastmod", namespaces=_NS) or url_el.findtext("lastmod")
        if loc:
            found.append(DiscoveredURL(url=loc.strip(), method="sitemap", lastmod=lastmod))
        if len(found) >= max_urls:
            break
    return found
