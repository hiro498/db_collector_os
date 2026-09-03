from __future__ import annotations

from db_collector_os.viability.config import ViabilityConfig
from db_collector_os.viability.scoring import (
    compute_competition_score,
    compute_db_fit_score,
    compute_demand_score,
    compute_priority_score,
)


def _config():
    return ViabilityConfig(
        scoring={
            "demand": {"reference_volume": 5000, "volume_points_max": 70, "breadth_points_per_kw": 3, "breadth_points_max": 30},
            "competition": {"strength_label_score": {"WEAK": 20, "MEDIUM": 55, "STRONG": 88}},
            "db_fit": {"points_per_axis": 8, "axis_points_max": 56, "longtail_ratio_points_max": 44},
            "priority": {"weights": {"demand": 0.4, "competition_ease": 0.35, "db_fit": 0.25}},
        }
    )


def test_demand_score_zero_volume_is_zero():
    score = compute_demand_score({"total_search_volume": 0, "kw_with_volume_count": 0}, _config())
    assert score == 0.0


def test_demand_score_increases_with_volume_and_breadth():
    low = compute_demand_score({"total_search_volume": 100, "kw_with_volume_count": 1}, _config())
    high = compute_demand_score({"total_search_volume": 5000, "kw_with_volume_count": 10}, _config())
    assert 0 < low < high <= 100


def test_demand_score_capped_at_100():
    score = compute_demand_score({"total_search_volume": 10_000_000, "kw_with_volume_count": 100}, _config())
    assert score == 100.0


def test_competition_score_all_weak_is_low():
    score = compute_competition_score({"weak_ratio": 1.0, "medium_ratio": 0.0, "strong_ratio": 0.0}, _config())
    assert score == 20.0


def test_competition_score_all_strong_is_high():
    score = compute_competition_score({"weak_ratio": 0.0, "medium_ratio": 0.0, "strong_ratio": 1.0}, _config())
    assert score == 88.0


def test_competition_score_none_ratio_is_zero():
    score = compute_competition_score({"weak_ratio": None}, _config())
    assert score == 0.0


def test_db_fit_score_rewards_axis_diversity_and_longtail_ratio():
    low = compute_db_fit_score({"longtail_kw_count": 1}, axis_count=1, total_candidate_count=2, config=_config())
    high = compute_db_fit_score({"longtail_kw_count": 9}, axis_count=6, total_candidate_count=10, config=_config())
    assert low < high
    assert high <= 100


def test_priority_score_blends_demand_ease_and_fit():
    score = compute_priority_score(demand_score=100, competition_score=0, db_fit_score=100, config=_config())
    assert score == 100.0
    score_bad = compute_priority_score(demand_score=0, competition_score=100, db_fit_score=0, config=_config())
    assert score_bad == 0.0
