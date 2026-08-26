"""Thin re-export: URL normalization lives in normalization.url; this module
adds the domain-extraction helper the fetch queue needs.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from ..normalization.url import normalize_url

__all__ = ["normalize_url", "extract_domain"]


def extract_domain(url: str) -> str:
    return urlsplit(url).netloc.lower()
