"""Canonical URL normalization, shared by the fetch queue and dedup/discovery."""

from __future__ import annotations

from urllib.parse import urldefrag, urlencode, parse_qsl, urlsplit, urlunsplit

_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "gclid", "fbclid", "yclid", "mc_cid", "mc_eid",
}


def normalize_url(url: str | None) -> str:
    if not url:
        return ""
    url, _frag = urldefrag(url.strip())
    parts = urlsplit(url)
    scheme = (parts.scheme or "http").lower()
    netloc = parts.netloc.lower()
    path = parts.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/") or "/"
    query_pairs = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in _TRACKING_PARAMS
    ]
    query_pairs.sort()
    query = urlencode(query_pairs)
    return urlunsplit((scheme, netloc, path, query, ""))
