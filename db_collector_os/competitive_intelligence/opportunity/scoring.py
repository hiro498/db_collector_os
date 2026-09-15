"""Combines component results into the section-3 aggregate scores plus
score_status/confidence (spec sections 3, 22, 23).

Missing-data handling (spec section 22 requires documenting the chosen
approach): this module RENORMALIZES weights over only the available
(OBSERVED or INFERRED) components -- an unavailable component's configured
weight share is redistributed proportionally among the components that
*are* available, rather than being silently treated as 0. `score_status`
is set independently of that renormalization, purely from how many/which
components were available, so a caller can always tell a well-supported
COMPLETE score from a thin NOT_ENOUGH_DATA one even though both go through
the same renormalized-weighted-average formula.
"""

from __future__ import annotations

from dataclasses import dataclass

from .components import ComponentResult
from .config import CONFIDENCE_VALUE_BY_STATUS, MIN_COMPONENTS_FOR_ANY_SCORE, OpportunityWeights
from .enums import Availability, ConfidenceLabel, ScoreStatus


@dataclass(frozen=True)
class AggregateScore:
    value: float | None
    score_status: str
    confidence_label: str
    confidence_value: float


def aggregate(components: dict[str, ComponentResult], weights: OpportunityWeights) -> AggregateScore:
    available = {name: c for name, c in components.items() if c.availability != Availability.UNAVAILABLE}
    observed_count = sum(1 for c in components.values() if c.availability == Availability.OBSERVED)
    total = len(components)

    if len(available) < MIN_COMPONENTS_FOR_ANY_SCORE:
        return AggregateScore(
            value=None, score_status=ScoreStatus.NOT_ENOUGH_DATA, confidence_label=ConfidenceLabel.LOW,
            confidence_value=CONFIDENCE_VALUE_BY_STATUS[ScoreStatus.NOT_ENOUGH_DATA],
        )

    weight_sum = sum(weights.component_weight(name) for name in available)
    if weight_sum <= 0:
        value = sum(c.value for c in available.values()) / len(available)
    else:
        value = sum(c.value * weights.component_weight(name) for name, c in available.items()) / weight_sum

    if len(available) == total:
        status = ScoreStatus.COMPLETE
    elif observed_count == 0:
        status = ScoreStatus.INTERNAL_ONLY
    else:
        status = ScoreStatus.PARTIAL

    label = {
        ScoreStatus.COMPLETE: ConfidenceLabel.HIGH,
        ScoreStatus.PARTIAL: ConfidenceLabel.MEDIUM,
        ScoreStatus.INTERNAL_ONLY: ConfidenceLabel.LOW,
        ScoreStatus.NOT_ENOUGH_DATA: ConfidenceLabel.LOW,
    }[status]
    return AggregateScore(
        value=round(value, 2), score_status=status, confidence_label=label,
        confidence_value=CONFIDENCE_VALUE_BY_STATUS[status],
    )
