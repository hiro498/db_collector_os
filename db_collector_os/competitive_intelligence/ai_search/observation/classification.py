"""Readiness vs Reality classification and opportunity signals (spec
sections 10-11). Every function here returns None whenever an input it
needs is unobserved -- a classification derived from a mix of known and
unknown facts would misrepresent certainty that doesn't exist, which is
exactly what spec section 2's NULL-safety rule is for. None of this
module computes a combined "Opportunity Score" -- spec section 11 is
explicit that only the individual boolean/enum signals ship in this phase.
"""

from __future__ import annotations

from .config import DEFAULT_CONFIG, ObservationConfig
from .enums import ReadinessVsRealityClass

_ORGANIC_BANDS = (3, 10, 20, 100)


def organic_band(rank: int | None) -> str:
    if rank is None:
        return "unknown"
    for band in _ORGANIC_BANDS:
        if rank <= band:
            return f"top{band}"
    return "outside_top100"


def any_cited(aio_cited: bool | None, ai_mode_cited: bool | None) -> bool | None:
    """True if either surface is known cited; False only if both are
    known and neither cited; None if citation status is entirely unknown."""
    if aio_cited is True or ai_mode_cited is True:
        return True
    if aio_cited is False and ai_mode_cited is False:
        return False
    return None


def classify_readiness_vs_reality(
    readiness_score: int | None, cited: bool | None, config: ObservationConfig = DEFAULT_CONFIG,
) -> str | None:
    if readiness_score is None or cited is None:
        return None
    high = readiness_score >= config.high_readiness_threshold
    if high and cited:
        return ReadinessVsRealityClass.HIGH_READINESS_CITED
    if high and not cited:
        return ReadinessVsRealityClass.HIGH_READINESS_NOT_CITED
    if not high and cited:
        return ReadinessVsRealityClass.LOW_READINESS_CITED
    return ReadinessVsRealityClass.LOW_READINESS_NOT_CITED


def classify_organic_aio_cross(organic_rank: int | None, aio_cited: bool | None) -> str | None:
    if aio_cited is None:
        return None
    return f"organic_{organic_band(organic_rank)}_aio_{'cited' if aio_cited else 'not_cited'}"


def compute_opportunity_signals(
    readiness_score: int | None, organic_rank: int | None, aio_cited: bool | None,
    ai_mode_cited: bool | None, fanout_visibility_rate: float | None,
    config: ObservationConfig = DEFAULT_CONFIG,
) -> dict[str, bool | None]:
    cited = any_cited(aio_cited, ai_mode_cited)
    high_readiness = None if readiness_score is None else readiness_score >= config.high_readiness_threshold
    root_visible = None if organic_rank is None else organic_rank <= 20
    low_rank = None if organic_rank is None else organic_rank > 20

    return {
        "signal_high_readiness_not_cited": (
            None if high_readiness is None or cited is None else bool(high_readiness and not cited)
        ),
        "signal_low_rank_but_cited": None if low_rank is None or cited is None else bool(low_rank and cited),
        "signal_high_rank_not_cited": (
            None if root_visible is None or cited is None else bool(root_visible and not cited)
        ),
        "signal_fanout_visible_not_root_visible": (
            None if fanout_visibility_rate is None or root_visible is None
            else bool(fanout_visibility_rate > 0 and not root_visible)
        ),
        "signal_aio_only": None if aio_cited is None or ai_mode_cited is None else bool(aio_cited and not ai_mode_cited),
        "signal_ai_mode_only": None if aio_cited is None or ai_mode_cited is None else bool(ai_mode_cited and not aio_cited),
        "signal_aio_and_ai_mode": None if aio_cited is None or ai_mode_cited is None else bool(aio_cited and ai_mode_cited),
        "signal_organic_only": (
            None if organic_rank is None or aio_cited is None or ai_mode_cited is None
            else bool(not aio_cited and not ai_mode_cited)
        ),
    }
