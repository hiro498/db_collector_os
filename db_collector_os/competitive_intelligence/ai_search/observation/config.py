"""Configurable defaults for the observation layer (spec sections 10, 12:
"thresholds and the default query-identity fields must be config, not
hardcoded"). Edit this module, not the classification/provider logic, to
retune.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ObservationConfig:
    default_country: str = "JP"
    default_language: str = "ja"
    default_device: str = "desktop"

    # spec section 10: "High" readiness threshold for the A/B/C/D
    # Readiness-vs-Reality classification. A page at or above this on
    # ai_citation_readiness_score (0-100) is "High Readiness".
    high_readiness_threshold: int = 60

    # spec section 5: organic rank bands used for organic_top3/10/20/100.
    organic_top_bands: tuple[int, ...] = (3, 10, 20, 100)


DEFAULT_CONFIG = ObservationConfig()
