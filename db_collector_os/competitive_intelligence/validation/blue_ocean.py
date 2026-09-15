"""Blue Ocean candidate flag (spec section 20). Explicitly NOT a combined
Blue Ocean Score -- just a boolean flag over already-computed PHASE 14
fields, with an honest INSUFFICIENT_DATA status whenever demand/
competition data isn't actually available (never "confirmed blue ocean"
from an unknown search volume).
"""

from __future__ import annotations

from .config import (
    BLUE_OCEAN_MAX_COMPETITOR_PROPRIETARY_SCORE,
    BLUE_OCEAN_MIN_COMMERCIAL_SCORE,
    BLUE_OCEAN_MIN_CONTENT_GAP_SCORE,
    BLUE_OCEAN_MIN_OPPORTUNITY_SCORE,
)
from .enums import BlueOceanCandidateStatus


def evaluate_blue_ocean_candidate(
    opportunity_score: float | None, commercial_score: float | None, content_gap_score: float | None,
    competitor_proprietary_score: float | None, demand_observed: bool, competitor_count: int | None,
) -> tuple[bool | None, str]:
    """Returns (blue_ocean_candidate, blue_ocean_candidate_status)."""
    if not demand_observed or competitor_count is None:
        return None, BlueOceanCandidateStatus.INSUFFICIENT_DATA
    if opportunity_score is None or commercial_score is None or content_gap_score is None:
        return None, BlueOceanCandidateStatus.INSUFFICIENT_DATA

    is_candidate = (
        opportunity_score >= BLUE_OCEAN_MIN_OPPORTUNITY_SCORE
        and commercial_score >= BLUE_OCEAN_MIN_COMMERCIAL_SCORE
        and content_gap_score >= BLUE_OCEAN_MIN_CONTENT_GAP_SCORE
        and (competitor_proprietary_score is None
             or competitor_proprietary_score <= BLUE_OCEAN_MAX_COMPETITOR_PROPRIETARY_SCORE)
    )
    return is_candidate, BlueOceanCandidateStatus.OK
