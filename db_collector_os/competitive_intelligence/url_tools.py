"""URL helpers for the crawler: normalization, same-host checks (deliberately
excluding subdomains, per spec section 6), pagination detection, and
crawl-target exclusion (section 9).

Builds on ``normalization.url.normalize_url`` and ``fetching.urlnorm`` rather
than re-implementing URL normalization.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from ..fetching.urlnorm import extract_domain
from ..normalization.url import normalize_url

__all__ = [
    "normalize_url",
    "extract_domain",
    "extract_host",
    "is_same_host",
    "is_pagination_url",
    "classify_non_crawlable",
    "url_slug",
]

_ASSET_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp", ".ico",
    ".css", ".js", ".mjs",
    ".mp4", ".mov", ".avi", ".webm", ".mp3", ".wav",
    ".zip", ".rar", ".7z", ".gz", ".tar",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".woff", ".woff2", ".ttf", ".eot",
)

_ADMIN_PATH_RE = re.compile(
    r"/(wp-admin|wp-login\.php|admin|administrator|management|cms|_next/|cgi-bin)(/|$)",
    re.IGNORECASE,
)

_PAGINATION_RE = re.compile(
    r"(?:[?&](?:page|p|paged)=\d+)|(?:/page/\d+/?$)|(?:/p\d+/?$)",
    re.IGNORECASE,
)


def extract_host(url: str) -> str:
    """Full host including port, lowercased -- the unit spec means by
    "domain" for subdomain-exclusion purposes (spec section 6)."""
    return urlsplit(url).netloc.lower()


def is_same_host(url: str, base_host: str) -> bool:
    """Exact host match only. A link to `blog.example.com` when the crawl
    target is `example.com` is a *different* host and is treated as a
    subdomain, which section 6 explicitly excludes -- not folded in via a
    suffix match the way discovery/internal_links.py's allowed_domains set
    normally would be for the entity-collection pipeline.
    """
    return extract_host(url) == base_host


def is_pagination_url(url: str) -> bool:
    return bool(_PAGINATION_RE.search(url))


def url_slug(url: str) -> str:
    path = urlsplit(url).path.rstrip("/")
    if not path:
        return ""
    return path.rsplit("/", 1)[-1]


def classify_non_crawlable(url: str, base_host: str) -> str | None:
    """Returns an ExclusionReason string if `url` should never be fetched as
    part of an affiliate-domain crawl, or None if it's a normal HTML
    candidate. Mirrors spec section 9's exclusion list; excluded URLs are
    still recorded (see repository.core.CrawlUrlRepository), never dropped
    silently.
    """
    from .enums import ExclusionReason

    if url.startswith("mailto:"):
        return ExclusionReason.MAILTO
    if url.startswith("tel:"):
        return ExclusionReason.TEL
    if url.startswith("javascript:"):
        return ExclusionReason.JAVASCRIPT_URL

    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return ExclusionReason.JAVASCRIPT_URL

    path_lower = parts.path.lower()
    if path_lower.endswith(_ASSET_EXTENSIONS):
        return ExclusionReason.NON_HTML_ASSET

    host = parts.netloc.lower()
    if host != base_host:
        # A different host: could be a genuine subdomain of base_host, or a
        # fully external domain. Both are out of scope for an
        # affiliate_domain crawl (section 6/9).
        if host.endswith("." + base_host) or base_host.endswith("." + host):
            return ExclusionReason.SUBDOMAIN
        return ExclusionReason.EXTERNAL_DOMAIN

    if _ADMIN_PATH_RE.search(parts.path):
        return ExclusionReason.ADMIN_URL

    return None
