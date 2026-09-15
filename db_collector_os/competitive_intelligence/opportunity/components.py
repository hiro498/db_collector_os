"""Pure-function component scoring (spec section 4). Every function here
takes plain, already-fetched values -- no DB access -- so each one is
independently testable and so `pipeline.py` is the only place that decides
*which* real rows feed them. Every function returns a `ComponentResult`
whose `availability` is OBSERVED, INFERRED, or UNAVAILABLE; `value` is
always None when `availability` is UNAVAILABLE -- no component here ever
substitutes 0 for "not observed".
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .config import DEMAND_VOLUME_SCALE_REFERENCE
from .enums import Availability


@dataclass(frozen=True)
class ComponentResult:
    value: float | None
    availability: str
    evidence: str


def _clip(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _unavailable(evidence: str) -> ComponentResult:
    return ComponentResult(value=None, availability=Availability.UNAVAILABLE, evidence=evidence)


def demand_score(metrics_row: dict | None) -> ComponentResult:
    """OBSERVED only from a real `ci_keyword_metrics` import row (spec
    section 15: never a fabricated/dummy volume)."""
    if not metrics_row or metrics_row.get("search_volume") is None:
        return _unavailable("no keyword_metrics import found for this query")
    volume = metrics_row["search_volume"]
    score = _clip(100.0 * math.log10(volume + 1) / math.log10(DEMAND_VOLUME_SCALE_REFERENCE + 1))
    return ComponentResult(
        value=round(score, 2), availability=Availability.OBSERVED,
        evidence=f"imported search_volume={volume} (source={metrics_row.get('source')})",
    )


def competition_score(competitor_count: int | None, competitor_strengths: list[float]) -> ComponentResult:
    """INFERRED: how crowded/strong the competitive set is, from our own
    crawl of those competitor pages -- not an external ranking-difficulty
    metric."""
    if not competitor_count:
        return _unavailable("no competitor pages identified for this keyword/page")
    avg_strength = sum(competitor_strengths) / len(competitor_strengths) if competitor_strengths else 0.0
    score = _clip(min(100.0, competitor_count * 8) * 0.5 + avg_strength * 0.5)
    return ComponentResult(
        value=round(score, 2), availability=Availability.INFERRED,
        evidence=f"{competitor_count} competitor page(s), avg strength={avg_strength:.1f}",
    )


def organic_gap_score(our_rank: int | None, competitor_best_rank: int | None) -> ComponentResult:
    """OBSERVED: both ranks come directly from PHASE 13 SERP observations.
    UNAVAILABLE unless at least the competitor's rank is observed (a
    known-rankable query with zero visibility for us is still meaningful;
    with no competitor observation either, this axis says nothing)."""
    if competitor_best_rank is None:
        return _unavailable("no organic SERP observation for any competitor on this query")
    if our_rank is None:
        return ComponentResult(
            value=80.0, availability=Availability.OBSERVED,
            evidence=f"competitor observed at rank {competitor_best_rank}; our page not found in organic observations",
        )
    gap = our_rank - competitor_best_rank
    score = _clip(max(0, gap) * 5)
    return ComponentResult(
        value=round(score, 2), availability=Availability.OBSERVED,
        evidence=f"our_rank={our_rank}, best_competitor_rank={competitor_best_rank}, gap={gap}",
    )


def ai_gap_score(readiness_vs_reality_class: str | None) -> ComponentResult:
    """OBSERVED only: requires our own PHASE 13 `readiness_vs_reality_class`
    to be non-None, which itself requires a known citation status (spec
    section 10: never assert an AI opportunity without external AI
    observation, readiness alone is not enough)."""
    if readiness_vs_reality_class is None:
        return _unavailable("no AIO/AI Mode citation observation for our page (readiness alone is not sufficient)")
    score_by_class = {"A": 10.0, "B": 90.0, "C": 20.0, "D": 55.0}
    score = score_by_class[readiness_vs_reality_class]
    return ComponentResult(
        value=score, availability=Availability.OBSERVED,
        evidence=f"readiness_vs_reality_class={readiness_vs_reality_class}",
    )


def fanout_gap_score(fanout_queries_observed: int, fanout_visibility_rate: float | None) -> ComponentResult:
    """OBSERVED: from PHASE 13 fan-out observations of our own page."""
    if not fanout_queries_observed or fanout_visibility_rate is None:
        return _unavailable("no fan-out observation recorded for our page yet")
    score = _clip((1 - fanout_visibility_rate) * 100)
    return ComponentResult(
        value=round(score, 2), availability=Availability.OBSERVED,
        evidence=f"fanout_visibility_rate={fanout_visibility_rate} over {fanout_queries_observed} observed subqueries",
    )


def content_gap_component(content_gap_score_value: float | None) -> ComponentResult:
    """INFERRED: wraps content_gap.py's own score (a real structural diff
    of two already-crawled pages' PHASE 12 evidence)."""
    if content_gap_score_value is None:
        return _unavailable("our page or the competitor page has no PHASE 12 AI Search Analysis yet")
    return ComponentResult(
        value=round(content_gap_score_value, 2), availability=Availability.INFERRED,
        evidence="structural diff of PHASE 12 evidence (subtopics/entities/questions/facts/comparisons) vs competitor",
    )


def _score_gap(our_score: int | float | None, competitor_score: int | float | None, label: str) -> ComponentResult:
    if our_score is None or competitor_score is None:
        return _unavailable(f"our page or the competitor page has no PHASE 12 {label} score")
    gap = competitor_score - our_score
    score = _clip(max(0, gap))
    return ComponentResult(
        value=round(score, 2), availability=Availability.INFERRED,
        evidence=f"our {label}={our_score}, competitor {label}={competitor_score}, gap={gap}",
    )


def proprietary_gap_score(our_score: int | None, competitor_score: int | None) -> ComponentResult:
    return _score_gap(our_score, competitor_score, "proprietary_information_score")


def freshness_gap_score(our_score: int | None, competitor_score: int | None) -> ComponentResult:
    return _score_gap(our_score, competitor_score, "evidence_freshness_score")


def source_strength_gap_score(our_score: int | None, competitor_score: int | None) -> ComponentResult:
    return _score_gap(our_score, competitor_score, "source_transparency_score")


def commercial_score(avg_commercial: float | None, keyword_count: int) -> ComponentResult:
    """INFERRED: our own PHASE 1 commercial-intent classification of the
    keywords this page targets -- a real classification of real content,
    not an external truth about buyer intent."""
    if avg_commercial is None or keyword_count == 0:
        return _unavailable("page has no PHASE 1 keyword scoring yet")
    return ComponentResult(
        value=round(_clip(avg_commercial), 2), availability=Availability.INFERRED,
        evidence=f"avg commercial_score across {keyword_count} target keyword(s)={avg_commercial:.1f}",
    )


def monetization_score(value: int | None) -> ComponentResult:
    """INFERRED: PHASE 1's own monetization_type/CTA-derived score."""
    if value is None:
        return _unavailable("page has no monetization scoring yet")
    return ComponentResult(
        value=round(_clip(value), 2), availability=Availability.INFERRED, evidence=f"ci_pages.monetization_score={value}",
    )
