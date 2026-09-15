"""Generic pairwise comparison (spec section 7): page-vs-page,
domain-vs-domain, and keyword-vs-keyword all reduce to the same
left/right/gap/winner/confidence shape, one row per comparison_dimension.
"""

from __future__ import annotations

from dataclasses import dataclass

from .enums import ComparisonWinner, ConfidenceLabel

# spec section 7's example dimensions.
DIMENSIONS = (
    "organic_rank", "aio_citation", "ai_mode_citation", "fanout_visibility", "readiness",
    "proprietary_information", "numeric_facts", "comparison_quality", "freshness",
    "commercial_intent", "monetization", "internal_link_strength",
)

# Whether a *lower* raw value is the winning side for this dimension (rank
# is the only one -- everything else is a 0-100-style score where higher
# wins).
_LOWER_IS_BETTER = {"organic_rank"}


@dataclass(frozen=True)
class ComparisonResult:
    left_value: float | None
    right_value: float | None
    gap_value: float | None
    winner: str
    confidence: str


def compare_dimension(
    dimension: str, left_value: float | None, right_value: float | None, confidence: str = ConfidenceLabel.MEDIUM,
) -> ComparisonResult:
    if left_value is None or right_value is None:
        return ComparisonResult(left_value, right_value, None, ComparisonWinner.UNKNOWN, ConfidenceLabel.LOW)
    higher_is_better = dimension not in _LOWER_IS_BETTER
    gap = left_value - right_value
    if gap == 0:
        winner = ComparisonWinner.TIE
    elif (gap > 0) == higher_is_better:
        winner = ComparisonWinner.LEFT
    else:
        winner = ComparisonWinner.RIGHT
    return ComparisonResult(left_value, right_value, gap, winner, confidence)
