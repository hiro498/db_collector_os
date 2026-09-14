from __future__ import annotations

from db_collector_os.competitive_intelligence.ai_search.weights import (
    READINESS_WEIGHTS,
    weighted_readiness_score,
)


def test_weights_sum_to_100():
    assert sum(READINESS_WEIGHTS.values()) == 100


def test_all_zero_components_score_zero():
    assert weighted_readiness_score({}) == 0


def test_all_max_components_score_100():
    all_max = {k: 100 for k in READINESS_WEIGHTS}
    assert weighted_readiness_score(all_max) == 100


def test_score_never_exceeds_100_even_with_out_of_range_inputs():
    over = {k: 999 for k in READINESS_WEIGHTS}
    assert weighted_readiness_score(over) <= 100


def test_score_never_negative_even_with_negative_inputs():
    under = {k: -50 for k in READINESS_WEIGHTS}
    assert weighted_readiness_score(under) >= 0


def test_unknown_component_keys_are_ignored_not_erroring():
    result = weighted_readiness_score({"not_a_real_component": 100})
    assert result == 0


def test_proprietary_information_is_the_heaviest_weight():
    """spec section 4: proprietary/primary information is explicitly the
    most important signal in this phase."""
    assert READINESS_WEIGHTS["proprietary_information"] == max(READINESS_WEIGHTS.values())
