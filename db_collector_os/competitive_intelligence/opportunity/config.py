"""Configurable weights and thresholds for the Opportunity Score layer
(spec section 21: "重みはconfig化してください... code内に散在したmagic numberは禁止").
Every number that shapes a score lives here, not inline in scoring.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# The 9 top-level weight buckets named in spec section 21's example, summing
# to 100. Two components (monetization_score, source_strength_gap_score --
# spec section 4) don't get their own top-level bucket in that example list;
# each instead takes a documented fixed share of its nearest sibling
# bucket's weight (see OpportunityWeights.component_weight below) rather
# than inventing an unlisted config key.
_MONETIZATION_SHARE_OF_COMMERCIAL = 0.4
_SOURCE_STRENGTH_SHARE_OF_PROPRIETARY = 0.3


@dataclass(frozen=True)
class OpportunityWeights:
    demand: float = 10.0
    competition: float = 10.0
    organic_gap: float = 15.0
    ai_gap: float = 20.0
    content_gap: float = 15.0
    commercial: float = 10.0
    fanout: float = 10.0
    freshness: float = 5.0
    proprietary: float = 5.0

    def total(self) -> float:
        return (self.demand + self.competition + self.organic_gap + self.ai_gap + self.content_gap
                + self.commercial + self.fanout + self.freshness + self.proprietary)

    def component_weight(self, component_name: str) -> float:
        """Maps each of the 11 stored components (spec section 4) onto its
        share of one of the 9 configured buckets above."""
        table = {
            "demand_score": self.demand,
            "competition_score": self.competition,
            "organic_gap_score": self.organic_gap,
            "ai_gap_score": self.ai_gap,
            "fanout_gap_score": self.fanout,
            "content_gap_score": self.content_gap,
            "freshness_gap_score": self.freshness,
            "proprietary_gap_score": self.proprietary * (1 - _SOURCE_STRENGTH_SHARE_OF_PROPRIETARY),
            "source_strength_gap_score": self.proprietary * _SOURCE_STRENGTH_SHARE_OF_PROPRIETARY,
            "commercial_score": self.commercial * (1 - _MONETIZATION_SHARE_OF_COMMERCIAL),
            "monetization_score": self.commercial * _MONETIZATION_SHARE_OF_COMMERCIAL,
        }
        if component_name not in table:
            raise ValueError(f"unknown opportunity component: {component_name!r}")
        return table[component_name]


DEFAULT_WEIGHTS = OpportunityWeights()

# All 11 stored components (spec section 4) in a fixed, documented order.
COMPONENT_NAMES: tuple[str, ...] = (
    "demand_score", "competition_score", "organic_gap_score", "ai_gap_score", "fanout_gap_score",
    "content_gap_score", "proprietary_gap_score", "freshness_gap_score", "commercial_score",
    "monetization_score", "source_strength_gap_score",
)

# score_status thresholds (spec section 22): how many of the 11 components
# must be available (OBSERVED or INFERRED) before a score is meaningful at
# all, vs. merely partial.
MIN_COMPONENTS_FOR_ANY_SCORE = 2

# High-readiness threshold reused from PHASE 13's own default (kept as a
# separate, explicit constant here rather than importing PHASE 13's config,
# so PHASE 14's threshold can be retuned independently later).
HIGH_READINESS_THRESHOLD = 60

# Demand normalization (spec section 15: never fabricate a volume; this is
# only the scale used to turn a REAL imported search_volume into a 0-100
# score). log10(reference + 1) maps to 100.
DEMAND_VOLUME_SCALE_REFERENCE = 10_000

# confidence_value assigned per score_status (spec section 23: "Internal-
# only dataだけなら高confidenceにしないこと" -- INTERNAL_ONLY is capped well
# below HIGH).
CONFIDENCE_VALUE_BY_STATUS: dict[str, float] = {
    "COMPLETE": 0.9,
    "PARTIAL": 0.55,
    "INTERNAL_ONLY": 0.3,
    "NOT_ENOUGH_DATA": 0.1,
}

# organic/AI "strong" cutoffs used by divergence classification (section 11).
ORGANIC_STRONG_RANK_MAX = 10
