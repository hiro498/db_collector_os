from __future__ import annotations

from db_collector_os.viability.config import ViabilityConfig
from db_collector_os.viability.judgement import decide_final_judgement


def _config(**overrides):
    fj = {
        "no_go_if_phase1_fail": True,
        "go_if_weak_ratio_at_least": 0.55,
        "no_go_if_strong_ratio_at_least": 0.70,
        "go_priority_min": 55,
        "hold_priority_min": 35,
    }
    fj.update(overrides)
    return ViabilityConfig(final_judgement=fj)


def test_phase1_fail_is_always_no_go_regardless_of_scores():
    judgement, reasoning = decide_final_judgement(
        "FAIL", {"weak_ratio": 1.0, "strong_ratio": 0.0}, 100, 0, 100, 100, _config()
    )
    assert judgement == "NO-GO"
    assert "Phase 1" in reasoning


def test_mostly_weak_longtail_is_go_shortcut():
    judgement, _ = decide_final_judgement(
        "PASS", {"weak_ratio": 0.6, "strong_ratio": 0.1}, 50, 40, 50, 40, _config()
    )
    assert judgement == "GO"


def test_mostly_strong_longtail_is_no_go_shortcut():
    judgement, _ = decide_final_judgement(
        "PASS", {"weak_ratio": 0.1, "strong_ratio": 0.8}, 90, 80, 90, 60, _config()
    )
    assert judgement == "NO-GO"


def test_falls_back_to_priority_score_thresholds():
    go, _ = decide_final_judgement("PASS", {"weak_ratio": 0.3, "strong_ratio": 0.3}, 60, 50, 60, 60, _config())
    assert go == "GO"

    hold, _ = decide_final_judgement("PASS", {"weak_ratio": 0.3, "strong_ratio": 0.3}, 40, 50, 40, 40, _config())
    assert hold == "HOLD"

    no_go, _ = decide_final_judgement("PASS", {"weak_ratio": 0.3, "strong_ratio": 0.3}, 20, 60, 20, 20, _config())
    assert no_go == "NO-GO"


def test_missing_competition_ratios_still_falls_back_to_priority():
    judgement, _ = decide_final_judgement(
        "PASS", {"weak_ratio": None, "strong_ratio": None}, 60, 50, 60, 60, _config()
    )
    assert judgement == "GO"
