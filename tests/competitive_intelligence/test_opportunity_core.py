"""Pure-function tests for the PHASE 14 building blocks: component scoring,
score aggregation/missing-data handling, divergence classification, generic
comparison, content gap diffing, competitor strength, reasons, and actions.
No DB involved -- see test_opportunity_pipeline.py for end-to-end coverage.
"""
from __future__ import annotations

from db_collector_os.competitive_intelligence.opportunity import components as C
from db_collector_os.competitive_intelligence.opportunity.actions import generate_actions
from db_collector_os.competitive_intelligence.opportunity.comparison import compare_dimension
from db_collector_os.competitive_intelligence.opportunity.competitor_strength import (
    CompetitorStrengthInputs, compute_competitor_strength, internal_link_strength_score,
)
from db_collector_os.competitive_intelligence.opportunity.config import DEFAULT_WEIGHTS, OpportunityWeights
from db_collector_os.competitive_intelligence.opportunity.content_gap import compute_content_gap
from db_collector_os.competitive_intelligence.opportunity.divergence import classify_organic_ai_divergence
from db_collector_os.competitive_intelligence.opportunity.enums import Availability, ScoreStatus
from db_collector_os.competitive_intelligence.opportunity.reasons import ReasonInputs, generate_reasons
from db_collector_os.competitive_intelligence.opportunity.scoring import aggregate


# ---- config ----

def test_default_weights_sum_to_100():
    assert DEFAULT_WEIGHTS.total() == 100.0


def test_component_weight_covers_all_eleven_components():
    from db_collector_os.competitive_intelligence.opportunity.config import COMPONENT_NAMES
    for name in COMPONENT_NAMES:
        assert DEFAULT_WEIGHTS.component_weight(name) > 0


def test_component_weight_unknown_name_raises():
    import pytest
    with pytest.raises(ValueError):
        DEFAULT_WEIGHTS.component_weight("not_a_real_component")


def test_monetization_and_source_strength_shares_still_sum_correctly():
    """monetization/source_strength don't have their own named config key --
    they take a documented share of commercial/proprietary respectively, so
    the two halves must still add up to the parent bucket."""
    w = DEFAULT_WEIGHTS
    assert abs(w.component_weight("commercial_score") + w.component_weight("monetization_score") - w.commercial) < 1e-9
    assert abs(w.component_weight("proprietary_gap_score") + w.component_weight("source_strength_gap_score") - w.proprietary) < 1e-9


# ---- components.py ----

def test_demand_score_unavailable_without_import():
    result = C.demand_score(None)
    assert result.availability == Availability.UNAVAILABLE
    assert result.value is None


def test_demand_score_never_fabricates_a_dummy_volume():
    """No metrics row at all -> UNAVAILABLE, never a guessed number."""
    result = C.demand_score({"search_volume": None, "source": "manual"})
    assert result.availability == Availability.UNAVAILABLE


def test_demand_score_observed_from_real_import():
    result = C.demand_score({"search_volume": 1000, "source": "manual"})
    assert result.availability == Availability.OBSERVED
    assert 0 < result.value <= 100


def test_competition_score_unavailable_with_no_competitors():
    result = C.competition_score(0, [])
    assert result.availability == Availability.UNAVAILABLE


def test_competition_score_inferred_with_competitors():
    result = C.competition_score(3, [50.0, 60.0])
    assert result.availability == Availability.INFERRED
    assert 0 <= result.value <= 100


def test_organic_gap_score_unavailable_with_no_competitor_observation():
    result = C.organic_gap_score(None, None)
    assert result.availability == Availability.UNAVAILABLE


def test_organic_gap_score_high_when_we_are_unobserved_but_competitor_ranks():
    result = C.organic_gap_score(None, 3)
    assert result.availability == Availability.OBSERVED
    assert result.value == 80.0


def test_organic_gap_score_zero_when_we_already_beat_competitor():
    result = C.organic_gap_score(1, 10)
    assert result.value == 0.0


def test_organic_gap_score_positive_when_behind():
    result = C.organic_gap_score(15, 1)
    assert result.value == 70.0


def test_ai_gap_score_unavailable_without_citation_observation():
    """spec section 10: never assert an AI opportunity from readiness alone."""
    result = C.ai_gap_score(None)
    assert result.availability == Availability.UNAVAILABLE


def test_ai_gap_score_high_for_class_b_high_readiness_not_cited():
    result = C.ai_gap_score("B")
    assert result.availability == Availability.OBSERVED
    assert result.value == 90.0


def test_ai_gap_score_low_for_class_a_high_readiness_cited():
    result = C.ai_gap_score("A")
    assert result.value == 10.0


def test_fanout_gap_score_unavailable_without_observation():
    result = C.fanout_gap_score(0, None)
    assert result.availability == Availability.UNAVAILABLE


def test_fanout_gap_score_from_visibility_rate():
    result = C.fanout_gap_score(5, 0.2)
    assert result.availability == Availability.OBSERVED
    assert result.value == 80.0


def test_content_gap_component_unavailable_without_analysis():
    result = C.content_gap_component(None)
    assert result.availability == Availability.UNAVAILABLE


def test_proprietary_gap_score_gap_and_negative_gap_clipped_to_zero():
    assert C.proprietary_gap_score(80, 20).value == 0.0  # we're already ahead
    assert C.proprietary_gap_score(20, 80).value == 60.0  # competitor ahead by 60


def test_commercial_score_unavailable_with_no_keywords():
    result = C.commercial_score(None, 0)
    assert result.availability == Availability.UNAVAILABLE


def test_monetization_score_from_real_value():
    result = C.monetization_score(0)
    assert result.availability == Availability.INFERRED
    assert result.value == 0.0


# ---- scoring.py ----

def _components(**overrides):
    from db_collector_os.competitive_intelligence.opportunity.config import COMPONENT_NAMES
    base = {name: C.ComponentResult(50.0, Availability.INFERRED, "test") for name in COMPONENT_NAMES}
    base.update(overrides)
    return base


def test_aggregate_not_enough_data_when_almost_nothing_available():
    components = {name: C.ComponentResult(None, Availability.UNAVAILABLE, "none") for name in _components()}
    result = aggregate(components, DEFAULT_WEIGHTS)
    assert result.value is None
    assert result.score_status == ScoreStatus.NOT_ENOUGH_DATA


def test_aggregate_complete_when_everything_available():
    result = aggregate(_components(), DEFAULT_WEIGHTS)
    assert result.score_status == ScoreStatus.COMPLETE
    assert result.value == 50.0
    assert result.confidence_label == "HIGH"


def test_aggregate_internal_only_when_zero_observed_but_some_inferred():
    components = _components(
        organic_gap_score=C.ComponentResult(None, Availability.UNAVAILABLE, "n/a"),
        ai_gap_score=C.ComponentResult(None, Availability.UNAVAILABLE, "n/a"),
        fanout_gap_score=C.ComponentResult(None, Availability.UNAVAILABLE, "n/a"),
        demand_score=C.ComponentResult(None, Availability.UNAVAILABLE, "n/a"),
    )
    result = aggregate(components, DEFAULT_WEIGHTS)
    assert result.score_status == ScoreStatus.INTERNAL_ONLY
    assert result.confidence_label != "HIGH", "internal-only data must never earn HIGH confidence"


def test_aggregate_partial_when_some_observed_some_missing():
    """PARTIAL requires at least one OBSERVED component alongside at least
    one missing one -- all-INFERRED-with-one-missing is INTERNAL_ONLY, not
    PARTIAL (covered by the INTERNAL_ONLY test above)."""
    components = _components(
        organic_gap_score=C.ComponentResult(40.0, Availability.OBSERVED, "serp"),
        demand_score=C.ComponentResult(None, Availability.UNAVAILABLE, "n/a"),
    )
    result = aggregate(components, DEFAULT_WEIGHTS)
    assert result.score_status == ScoreStatus.PARTIAL


def test_aggregate_renormalizes_over_available_components_only():
    """Missing components must not silently count as 0 -- removing an
    UNAVAILABLE component from an otherwise-uniform set must not change
    the aggregate value at all."""
    components = _components(demand_score=C.ComponentResult(None, Availability.UNAVAILABLE, "n/a"))
    result = aggregate(components, DEFAULT_WEIGHTS)
    assert result.value == 50.0


def test_aggregate_never_exceeds_100_or_goes_below_0():
    components = {name: C.ComponentResult(100.0, Availability.OBSERVED, "max") for name in _components()}
    result = aggregate(components, DEFAULT_WEIGHTS)
    assert result.value == 100.0
    components_zero = {name: C.ComponentResult(0.0, Availability.OBSERVED, "min") for name in _components()}
    result_zero = aggregate(components_zero, DEFAULT_WEIGHTS)
    assert result_zero.value == 0.0


def test_custom_weights_are_actually_used():
    heavy_demand = OpportunityWeights(demand=90, competition=1.25, organic_gap=1.25, ai_gap=1.25, content_gap=1.25,
                                       commercial=1.25, fanout=1.25, freshness=1.25, proprietary=1.25)
    components = _components(demand_score=C.ComponentResult(100.0, Availability.OBSERVED, "high demand"))
    result = aggregate(components, heavy_demand)
    assert result.value > 90.0  # heavily weighted toward the one high-value component


# ---- divergence.py ----

def test_divergence_not_observed_without_both_signals():
    score, cls = classify_organic_ai_divergence(None, True)
    assert score is None and cls == "not_observed"


def test_divergence_organic_strong_ai_weak():
    score, cls = classify_organic_ai_divergence(3, False)
    assert cls == "organic_strong_ai_weak"
    assert score == 90.0


def test_divergence_organic_weak_ai_strong():
    score, cls = classify_organic_ai_divergence(50, True)
    assert cls == "organic_weak_ai_strong"


def test_divergence_strong_both_and_weak_both():
    assert classify_organic_ai_divergence(3, True)[1] == "strong_both"
    assert classify_organic_ai_divergence(50, False)[1] == "weak_both"


# ---- comparison.py ----

def test_compare_dimension_unknown_winner_when_either_side_missing():
    result = compare_dimension("readiness", None, 50.0)
    assert result.winner == "unknown"
    assert result.confidence == "LOW"


def test_compare_dimension_organic_rank_lower_is_better():
    result = compare_dimension("organic_rank", 3.0, 10.0)
    assert result.winner == "left"  # rank 3 beats rank 10


def test_compare_dimension_readiness_higher_is_better():
    result = compare_dimension("readiness", 80.0, 40.0)
    assert result.winner == "left"


def test_compare_dimension_tie():
    result = compare_dimension("readiness", 50.0, 50.0)
    assert result.winner == "tie"


# ---- content_gap.py ----

def test_content_gap_missing_items_are_real_diffs_not_fabricated():
    result = compute_content_gap(
        our_keywords={"a"}, competitor_keywords={"a", "b", "c"},
        our_subtopics=set(), competitor_subtopics={"見出し1"},
        our_entities=set(), competitor_entities=set(),
        our_questions=set(), competitor_questions=set(),
        our_numeric_facts=[], competitor_numeric_facts=["42店舗を調査"],
        our_comparison_structures=set(), competitor_comparison_structures={"table"},
        our_primary_signals=set(), competitor_primary_signals={"firsthand_signal"},
        our_freshness_events=[], competitor_freshness_events=["ranking_delta"],
        our_internal_link_topics=set(), competitor_internal_link_topics=set(),
    )
    assert result.missing_keywords == ["b", "c"]
    assert result.missing_subtopics == ["見出し1"]
    assert result.missing_numeric_facts == ["42店舗を調査"]
    assert result.missing_comparison_dimensions == ["table"]
    assert result.missing_primary_information == ["firsthand_signal"]
    assert result.missing_freshness_evidence == ["ranking_delta"]
    assert result.content_gap_score > 0


def test_content_gap_zero_when_our_page_has_everything():
    shared = {"a", "b"}
    result = compute_content_gap(
        our_keywords=shared, competitor_keywords=shared, our_subtopics=shared, competitor_subtopics=shared,
        our_entities=shared, competitor_entities=shared, our_questions=shared, competitor_questions=shared,
        our_numeric_facts=list(shared), competitor_numeric_facts=list(shared),
        our_comparison_structures=shared, competitor_comparison_structures=shared,
        our_primary_signals=shared, competitor_primary_signals=shared,
        our_freshness_events=list(shared), competitor_freshness_events=list(shared),
        our_internal_link_topics=shared, competitor_internal_link_topics=shared,
    )
    assert result.content_gap_score == 0.0
    assert all(len(m) == 0 for m in (
        result.missing_keywords, result.missing_subtopics, result.missing_entities, result.missing_questions,
    ))


def test_content_gap_score_never_exceeds_100():
    result = compute_content_gap(
        our_keywords=set(), competitor_keywords={"a", "b", "c", "d"},
        our_subtopics=set(), competitor_subtopics={"x", "y"},
        our_entities=set(), competitor_entities={"z"},
        our_questions=set(), competitor_questions={"q"},
        our_numeric_facts=[], competitor_numeric_facts=["1", "2"],
        our_comparison_structures=set(), competitor_comparison_structures={"table", "list"},
        our_primary_signals=set(), competitor_primary_signals={"firsthand_signal", "methodology_signal"},
        our_freshness_events=[], competitor_freshness_events=["a", "b"],
        our_internal_link_topics=set(), competitor_internal_link_topics={"t"},
    )
    assert result.content_gap_score <= 100.0


# ---- competitor_strength.py ----

def test_competitor_strength_composite_ignores_unavailable_axes():
    inputs = CompetitorStrengthInputs(
        organic_rank=None, ai_cited=None, subtopic_count=0, related_question_count=0, entity_coverage_count=0,
        proprietary_information_score=None, evidence_freshness_score=None, inbound_link_count=0, pagerank=0.0,
        monetization_score=None,
    )
    strength = compute_competitor_strength(inputs)
    assert strength.organic_strength is None
    assert strength.ai_strength is None
    assert strength.competitor_strength_score is not None  # content_strength + internal_link_strength always compute


def test_internal_link_strength_score_monotonic_in_inbound_count():
    assert internal_link_strength_score(5, 0.1) > internal_link_strength_score(1, 0.1)


# ---- reasons.py ----

def _reason_inputs(**overrides) -> ReasonInputs:
    base = dict(
        readiness_vs_reality_class=None, our_organic_rank=None, ai_cited=None, our_proprietary=None,
        competitor_proprietary=None, our_freshness=None, competitor_freshness=None, our_comparison=None,
        competitor_comparison=None, our_numeric_facts=None, competitor_numeric_facts=None, fanout_gap_value=None,
        content_gap_value=None, commercial_value=None, monetization_value=None, divergence_class="not_observed",
        organic_gap_value=None,
    )
    base.update(overrides)
    return ReasonInputs(**base)


def test_reasons_high_readiness_not_cited_is_top_impact():
    reasons = generate_reasons(_reason_inputs(readiness_vs_reality_class="B"))
    codes = [r.reason_code for r in reasons]
    assert "HIGH_READINESS_NOT_CITED" in codes
    assert reasons[0].reason_code == "HIGH_READINESS_NOT_CITED"


def test_reasons_empty_when_nothing_triggers():
    assert generate_reasons(_reason_inputs()) == []


def test_reasons_competitor_weak_proprietary_only_fires_when_we_are_ahead():
    reasons = generate_reasons(_reason_inputs(our_proprietary=80, competitor_proprietary=20))
    assert any(r.reason_code == "COMPETITOR_WEAK_PROPRIETARY" for r in reasons)
    reasons_reverse = generate_reasons(_reason_inputs(our_proprietary=20, competitor_proprietary=80))
    assert not any(r.reason_code == "COMPETITOR_WEAK_PROPRIETARY" for r in reasons_reverse)


def test_reasons_sorted_by_impact_descending():
    reasons = generate_reasons(_reason_inputs(readiness_vs_reality_class="B", commercial_value=70.0))
    impacts = [r.impact_score for r in reasons]
    assert impacts == sorted(impacts, reverse=True)


# ---- actions.py ----

def test_actions_content_gap_produces_specific_add_actions():
    from db_collector_os.competitive_intelligence.opportunity.content_gap import ContentGapResult

    gap = ContentGapResult(
        missing_keywords=[], missing_subtopics=[], missing_entities=[], missing_questions=[],
        missing_numeric_facts=["fact"], missing_comparison_dimensions=["table"], missing_primary_information=[],
        missing_freshness_evidence=[], missing_internal_link_topics=[], content_gap_score=50.0,
    )
    actions = generate_actions([], gap, page_exists=True, target_page="p1", target_keyword=None)
    codes = {a.action_code for a in actions}
    assert "ADD_NUMERIC_FACTS" in codes
    assert "ADD_COMPARISON_DIMENSIONS" in codes
    assert "ADD_PROPRIETARY_DATA" not in codes  # no missing_primary_information in this fixture


def test_actions_create_new_page_vs_improve_existing_page():
    reasons = generate_reasons(_reason_inputs(readiness_vs_reality_class="B"))
    improve = generate_actions(reasons, None, page_exists=True, target_page="p1", target_keyword=None)
    create = generate_actions(reasons, None, page_exists=False, target_page=None, target_keyword="k1")
    assert any(a.action_code == "IMPROVE_EXISTING_PAGE" for a in improve)
    assert any(a.action_code == "CREATE_NEW_PAGE" for a in create)


def test_actions_never_contain_generated_body_text():
    reasons = generate_reasons(_reason_inputs(readiness_vs_reality_class="B"))
    actions = generate_actions(reasons, None, page_exists=True, target_page="p1", target_keyword=None)
    for a in actions:
        assert not hasattr(a, "body")
        assert not hasattr(a, "content")


def test_actions_deduplicated_keeping_highest_priority():
    reasons = generate_reasons(_reason_inputs(readiness_vs_reality_class="B", our_organic_rank=5, ai_cited=False))
    actions = generate_actions(reasons, None, page_exists=True, target_page="p1", target_keyword=None)
    keys = [(a.action_code, a.reason_code) for a in actions]
    assert len(keys) == len(set(keys))
