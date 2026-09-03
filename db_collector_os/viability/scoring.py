"""Demand / Competition / DB Fit -> Priority scoring (spec section 7). All
weights and reference values come from config/viability.yaml -- nothing
here is a magic number.
"""

from __future__ import annotations

import math
from typing import Any

from .config import ViabilityConfig


def compute_demand_score(demand_summary: dict[str, Any], config: ViabilityConfig) -> float:
    cfg = config.scoring.get("demand", {})
    reference_volume = cfg.get("reference_volume", 5000)
    volume_points_max = cfg.get("volume_points_max", 70)
    breadth_per_kw = cfg.get("breadth_points_per_kw", 3)
    breadth_max = cfg.get("breadth_points_max", 30)

    total_volume = demand_summary.get("total_search_volume", 0) or 0
    if reference_volume > 0 and total_volume > 0:
        volume_points = volume_points_max * min(1.0, math.log1p(total_volume) / math.log1p(reference_volume))
    else:
        volume_points = 0.0

    breadth_points = min(breadth_max, breadth_per_kw * (demand_summary.get("kw_with_volume_count", 0) or 0))
    return round(min(100.0, volume_points + breadth_points), 1)


def compute_competition_score(competition_summary: dict[str, Any], config: ViabilityConfig) -> float:
    """0-100, higher = harder to win. Weighted average of the theme's
    WEAK/MEDIUM/STRONG ratios against the configured per-label scores."""
    cfg = config.scoring.get("competition", {}).get("strength_label_score", {})
    weak = cfg.get("WEAK", 20)
    medium = cfg.get("MEDIUM", 55)
    strong = cfg.get("STRONG", 88)

    weak_ratio = competition_summary.get("weak_ratio")
    if weak_ratio is None:
        return 0.0
    medium_ratio = competition_summary.get("medium_ratio") or 0.0
    strong_ratio = competition_summary.get("strong_ratio") or 0.0
    score = weak_ratio * weak + medium_ratio * medium + strong_ratio * strong
    return round(score, 1)


def compute_db_fit_score(
    demand_summary: dict[str, Any], axis_count: int, total_candidate_count: int, config: ViabilityConfig
) -> float:
    """Rewards a theme that has many independent search axes AND a high
    proportion of longtail keywords -- i.e. it's actually shaped like a
    database (many structured detail pages), not a single article."""
    cfg = config.scoring.get("db_fit", {})
    points_per_axis = cfg.get("points_per_axis", 8)
    axis_points_max = cfg.get("axis_points_max", 56)
    longtail_points_max = cfg.get("longtail_ratio_points_max", 44)

    axis_points = min(axis_points_max, points_per_axis * axis_count)

    longtail_count = demand_summary.get("longtail_kw_count", 0) or 0
    longtail_ratio = (longtail_count / total_candidate_count) if total_candidate_count else 0.0
    longtail_points = longtail_points_max * longtail_ratio

    return round(min(100.0, axis_points + longtail_points), 1)


def compute_priority_score(demand_score: float, competition_score: float, db_fit_score: float, config: ViabilityConfig) -> float:
    weights = config.scoring.get("priority", {}).get(
        "weights", {"demand": 0.4, "competition_ease": 0.35, "db_fit": 0.25}
    )
    ease = 100.0 - competition_score
    score = (
        demand_score * weights.get("demand", 0.4)
        + ease * weights.get("competition_ease", 0.35)
        + db_fit_score * weights.get("db_fit", 0.25)
    )
    return round(max(0.0, min(100.0, score)), 1)
