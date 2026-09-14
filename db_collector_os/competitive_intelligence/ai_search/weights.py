"""Configurable weights for ai_citation_readiness_score (spec section 20:
"weights must not be hardcoded from gut feeling from the start -- store
every signal separately and make weights configurable"). Each named
weight below is the maximum contribution of one already-0-100-normalized
component score toward the 100-point total; edit this dict, not the
scorer's arithmetic, to retune.
"""

from __future__ import annotations

READINESS_WEIGHTS: dict[str, int] = {
    "proprietary_information": 30,
    "comparison_information": 15,
    "numeric_fact_quality": 15,
    "evidence_freshness": 15,
    "aio_extractability": 10,
    "ai_mode_content_coverage": 10,
    "fanout_content_coverage": 3,
    "source_transparency": 2,
}

assert sum(READINESS_WEIGHTS.values()) == 100, "READINESS_WEIGHTS must sum to 100"


def weighted_readiness_score(component_scores_0_100: dict[str, int]) -> int:
    """`component_scores_0_100` maps the same keys as READINESS_WEIGHTS to
    an already-0-100 score for that component. Missing keys contribute 0."""
    total = 0.0
    for key, weight in READINESS_WEIGHTS.items():
        component = max(0, min(100, component_scores_0_100.get(key, 0)))
        total += component * weight / 100.0
    return max(0, min(100, round(total)))
