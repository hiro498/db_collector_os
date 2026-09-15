"""Organic vs AI visibility divergence (spec section 11)."""

from __future__ import annotations

from .config import ORGANIC_STRONG_RANK_MAX
from .enums import DivergenceClass


def classify_organic_ai_divergence(organic_rank: int | None, ai_cited: bool | None) -> tuple[float | None, str]:
    """Returns (organic_ai_divergence_score, class). Score is 0-100 --
    higher means a bigger gap between the two channels (in either
    direction) -- and is None (class NOT_OBSERVED) unless both organic rank
    and AI citation status are actually known."""
    if organic_rank is None or ai_cited is None:
        return None, DivergenceClass.NOT_OBSERVED

    organic_strong = organic_rank <= ORGANIC_STRONG_RANK_MAX
    if organic_strong and not ai_cited:
        return 90.0, DivergenceClass.ORGANIC_STRONG_AI_WEAK
    if not organic_strong and ai_cited:
        return 90.0, DivergenceClass.ORGANIC_WEAK_AI_STRONG
    if organic_strong and ai_cited:
        return 10.0, DivergenceClass.STRONG_BOTH
    return 50.0, DivergenceClass.WEAK_BOTH
