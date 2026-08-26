"""Shared types for discovery methods."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DiscoveredURL:
    url: str
    method: str
    lastmod: str | None = None
    confidence: float = 0.5
