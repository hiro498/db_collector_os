"""Opportunity Reason Engine (spec sections 17-18): explains *why* a score
is high, not just the number. Every reason carries a `reason_code` from a
fixed vocabulary (enums.ReasonCode) plus a human-readable `reason_text`, an
`impact_score`, and an `evidence_reference` pointing at the real
observation/computation that produced it.
"""

from __future__ import annotations

from dataclasses import dataclass

from .enums import DivergenceClass, ReasonCode

_HIGH_THRESHOLD = 60.0
# Matches PHASE 13's own "root_visible" band (ci_ai_page_visibility opportunity
# signals): top20 counts as "ranking well enough to be visible at all",
# distinct from divergence.py's stricter top10 "organic strong" cutoff.
_VISIBLE_ORGANIC_RANK_MAX = 20


@dataclass(frozen=True)
class Reason:
    reason_code: str
    reason_text: str
    impact_score: float
    evidence_reference: str


@dataclass(frozen=True)
class ReasonInputs:
    readiness_vs_reality_class: str | None
    our_organic_rank: int | None
    ai_cited: bool | None
    our_proprietary: int | None
    competitor_proprietary: int | None
    our_freshness: int | None
    competitor_freshness: int | None
    our_comparison: int | None
    competitor_comparison: int | None
    our_numeric_facts: int | None
    competitor_numeric_facts: int | None
    fanout_gap_value: float | None
    content_gap_value: float | None
    commercial_value: float | None
    monetization_value: float | None
    divergence_class: str
    organic_gap_value: float | None


def generate_reasons(i: ReasonInputs) -> list[Reason]:
    reasons: list[Reason] = []

    if i.readiness_vs_reality_class == "B":
        reasons.append(Reason(
            ReasonCode.HIGH_READINESS_NOT_CITED,
            "Our page has high AI Citation Readiness but is not cited by AIO/AI Mode.",
            90.0, "ci_ai_page_visibility.readiness_vs_reality_class=B",
        ))

    if i.our_organic_rank is not None and i.our_organic_rank <= _VISIBLE_ORGANIC_RANK_MAX and i.ai_cited is False:
        reasons.append(Reason(
            ReasonCode.HIGH_RANK_NOT_CITED,
            "Our page ranks well organically but is not cited by AI search.",
            75.0, f"organic_rank={i.our_organic_rank}, ai_cited=False",
        ))

    if i.our_organic_rank is not None and i.our_organic_rank > _VISIBLE_ORGANIC_RANK_MAX and i.ai_cited is True:
        reasons.append(Reason(
            ReasonCode.LOW_RANK_CITED,
            "Our page ranks poorly organically but is already cited by AI search -- organic upside remains.",
            50.0, f"organic_rank={i.our_organic_rank}, ai_cited=True",
        ))

    if i.our_proprietary is not None and i.competitor_proprietary is not None and i.our_proprietary > i.competitor_proprietary:
        reasons.append(Reason(
            ReasonCode.COMPETITOR_WEAK_PROPRIETARY,
            "Competitor has weaker proprietary/primary information than our page.",
            float(i.our_proprietary - i.competitor_proprietary),
            f"our proprietary_information_score={i.our_proprietary}, competitor={i.competitor_proprietary}",
        ))

    if i.our_freshness is not None and i.competitor_freshness is not None and i.our_freshness > i.competitor_freshness:
        reasons.append(Reason(
            ReasonCode.COMPETITOR_WEAK_FRESHNESS,
            "Competitor's evidence freshness is weaker than our page's.",
            float(i.our_freshness - i.competitor_freshness),
            f"our evidence_freshness_score={i.our_freshness}, competitor={i.competitor_freshness}",
        ))

    if i.our_comparison is not None and i.competitor_comparison is not None and i.our_comparison > i.competitor_comparison:
        reasons.append(Reason(
            ReasonCode.COMPETITOR_WEAK_COMPARISON,
            "Competitor's comparison content is weaker than our page's.",
            float(i.our_comparison - i.competitor_comparison),
            f"our comparison_information_score={i.our_comparison}, competitor={i.competitor_comparison}",
        ))

    if i.our_numeric_facts is not None and i.competitor_numeric_facts is not None and i.our_numeric_facts > i.competitor_numeric_facts:
        reasons.append(Reason(
            ReasonCode.COMPETITOR_WEAK_NUMERIC_FACTS,
            "Competitor has fewer/weaker numeric facts than our page.",
            float(i.our_numeric_facts - i.competitor_numeric_facts),
            f"our numeric_fact_quality_score={i.our_numeric_facts}, competitor={i.competitor_numeric_facts}",
        ))

    if i.fanout_gap_value is not None and i.fanout_gap_value >= _HIGH_THRESHOLD:
        reasons.append(Reason(
            ReasonCode.FANOUT_GAP,
            "Fan-out subquery coverage is incomplete relative to what has been observed.",
            i.fanout_gap_value, f"fanout_gap_score={i.fanout_gap_value}",
        ))

    if i.content_gap_value is not None and i.content_gap_value >= 30.0:
        reasons.append(Reason(
            ReasonCode.CONTENT_GAP,
            "Competitor covers keywords/subtopics/entities/facts our page is missing.",
            i.content_gap_value, f"content_gap_score={i.content_gap_value}",
        ))

    if i.commercial_value is not None and i.commercial_value >= _HIGH_THRESHOLD:
        reasons.append(Reason(
            ReasonCode.COMMERCIAL_HIGH,
            "Commercial intent for this keyword/page is high.",
            i.commercial_value, f"commercial_score={i.commercial_value}",
        ))

    if i.monetization_value is not None and i.monetization_value >= _HIGH_THRESHOLD:
        reasons.append(Reason(
            ReasonCode.MONETIZATION_HIGH,
            "Monetization potential for this page is high.",
            i.monetization_value, f"monetization_score={i.monetization_value}",
        ))

    our_stronger_axes = sum(
        1 for our, comp in (
            (i.our_proprietary, i.competitor_proprietary), (i.our_freshness, i.competitor_freshness),
            (i.our_comparison, i.competitor_comparison), (i.our_numeric_facts, i.competitor_numeric_facts),
        ) if our is not None and comp is not None and our > comp
    )
    if our_stronger_axes >= 2:
        reasons.append(Reason(
            ReasonCode.OUR_CONTENT_STRONGER,
            "Our page's content is stronger than the competitor's across multiple axes.",
            float(our_stronger_axes) * 20.0, f"{our_stronger_axes} axes favor our page",
        ))

    if i.divergence_class in (DivergenceClass.ORGANIC_STRONG_AI_WEAK, DivergenceClass.ORGANIC_WEAK_AI_STRONG):
        reasons.append(Reason(
            ReasonCode.ORGANIC_AI_DIVERGENCE,
            f"Organic and AI visibility diverge for this page ({i.divergence_class}).",
            70.0, f"organic_ai_divergence_class={i.divergence_class}",
        ))

    if i.organic_gap_value is not None and i.organic_gap_value >= _HIGH_THRESHOLD:
        reasons.append(Reason(
            ReasonCode.ORGANIC_GAP,
            "Competitor organic rank is meaningfully better than ours.",
            i.organic_gap_value, f"organic_gap_score={i.organic_gap_value}",
        ))

    return sorted(reasons, key=lambda r: r.impact_score, reverse=True)
