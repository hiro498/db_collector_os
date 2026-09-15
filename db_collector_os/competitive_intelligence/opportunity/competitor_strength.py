"""Competitor Strength Score (spec section 8): never a single black-box
number -- each sub-strength is stored individually, and the optional
composite is only ever a documented average of the parts that are
actually available.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CompetitorStrengthInputs:
    organic_rank: int | None            # lower is stronger
    ai_cited: bool | None                # aio_cited or ai_mode_cited (any_cited)
    subtopic_count: int
    related_question_count: int
    entity_coverage_count: int
    proprietary_information_score: int | None
    evidence_freshness_score: int | None
    inbound_link_count: int
    pagerank: float
    monetization_score: int | None


def _organic_strength(rank: int | None) -> float | None:
    if rank is None:
        return None
    return max(0.0, min(100.0, 100.0 - (rank - 1) * 5))


def _ai_strength(ai_cited: bool | None) -> float | None:
    if ai_cited is None:
        return None
    return 90.0 if ai_cited else 10.0


def _content_strength(subtopic_count: int, related_question_count: int, entity_coverage_count: int) -> float:
    return max(0.0, min(100.0, min(subtopic_count, 6) * 8 + min(related_question_count, 5) * 8
                         + min(entity_coverage_count, 10) * 3))


def internal_link_strength_score(inbound_link_count: int, pagerank: float) -> float:
    return max(0.0, min(100.0, inbound_link_count * 10 + pagerank * 100))


@dataclass(frozen=True)
class CompetitorStrength:
    organic_strength: float | None
    ai_strength: float | None
    content_strength: float
    proprietary_strength: float | None
    freshness_strength: float | None
    internal_link_strength: float
    monetization_strength: float | None
    competitor_strength_score: float | None


def compute_competitor_strength(inputs: CompetitorStrengthInputs) -> CompetitorStrength:
    organic = _organic_strength(inputs.organic_rank)
    ai = _ai_strength(inputs.ai_cited)
    content = _content_strength(inputs.subtopic_count, inputs.related_question_count, inputs.entity_coverage_count)
    proprietary = float(inputs.proprietary_information_score) if inputs.proprietary_information_score is not None else None
    freshness = float(inputs.evidence_freshness_score) if inputs.evidence_freshness_score is not None else None
    internal_links = internal_link_strength_score(inputs.inbound_link_count, inputs.pagerank)
    monetization = float(inputs.monetization_score) if inputs.monetization_score is not None else None

    parts = [p for p in (organic, ai, content, proprietary, freshness, internal_links, monetization) if p is not None]
    composite = round(sum(parts) / len(parts), 2) if parts else None

    return CompetitorStrength(
        organic_strength=organic, ai_strength=ai, content_strength=round(content, 2),
        proprietary_strength=proprietary, freshness_strength=freshness,
        internal_link_strength=round(internal_links, 2), monetization_strength=monetization,
        competitor_strength_score=composite,
    )
