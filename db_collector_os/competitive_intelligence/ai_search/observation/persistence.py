"""Citation persistence (spec section 8): a single cited observation is
weak evidence on its own -- what matters is whether citation holds up
across repeated observations over time. `citation_frequency` alone
answers "what share of observations cited this page"; `persistence_score`
additionally discounts a frequency computed from very few observations,
so "1 observation, cited once" does not equal "5 observations, cited
every time".
"""

from __future__ import annotations

_CONFIDENCE_SATURATION_OBSERVATIONS = 5


def citation_frequency(observation_count: int, cited_observation_count: int) -> float | None:
    if observation_count <= 0:
        return None
    return round(cited_observation_count / observation_count, 4)


def persistence_score(observation_count: int, cited_observation_count: int) -> float | None:
    """0-100, or None if there is no observation at all yet."""
    freq = citation_frequency(observation_count, cited_observation_count)
    if freq is None:
        return None
    confidence = min(1.0, observation_count / _CONFIDENCE_SATURATION_OBSERVATIONS)
    return round(freq * confidence * 100, 2)
