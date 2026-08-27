"""Shared types for discovery methods."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DiscoveredURL:
    url: str
    method: str
    lastmod: str | None = None
    confidence: float = 0.5
    # A stable identifier extracted from the URL itself (e.g. a numeric
    # product ID captured by a job's `discovery.product_url_pattern`), used
    # to fingerprint/dedup candidates that reach the same real-world entity
    # through different URLs (different slug, tracking params, ...) before a
    # single fetch is even made. None when no such pattern applies.
    stable_id: str | None = None
