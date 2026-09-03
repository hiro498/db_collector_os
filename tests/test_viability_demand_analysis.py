from __future__ import annotations

from db_collector_os.viability.config import ViabilityConfig
from db_collector_os.viability.demand_analysis import summarize_demand


def _config(**gate_overrides):
    gate = {
        "min_total_search_volume": 300,
        "min_kw_with_volume_count": 3,
        "min_longtail_kw_count": 3,
        "small_volume_threshold": 10,
    }
    gate.update(gate_overrides)
    return ViabilityConfig(phase1_gate=gate)


def _row(keyword, volume, is_main=False):
    return {"keyword": keyword, "is_main": is_main, "monthly_search_volume": volume}


def test_passes_when_thresholds_met():
    rows = [
        _row("main", 500, is_main=True),
        _row("lt1", 200),
        _row("lt2", 150),
        _row("lt3", 100),
    ]
    summary = summarize_demand(rows, _config())
    assert summary["phase1_result"] == "PASS"
    assert summary["total_search_volume"] == 950
    assert summary["main_kw_volume"] == 500
    assert summary["longtail_kw_count"] == 3
    assert summary["kw_with_volume_count"] == 4
    assert summary["kw_zero_or_low_count"] == 0
    assert "Phase 2" in summary["reasoning"]


def test_fails_on_total_volume_floor():
    rows = [_row("main", 50, is_main=True), _row("lt1", 20), _row("lt2", 15), _row("lt3", 5)]
    summary = summarize_demand(rows, _config())
    assert summary["phase1_result"] == "FAIL"
    assert "総検索需要" in summary["reasoning"]


def test_fails_on_longtail_count_floor_even_with_enough_volume():
    rows = [_row("main", 1000, is_main=True)]
    summary = summarize_demand(rows, _config())
    assert summary["phase1_result"] == "FAIL"
    assert summary["longtail_kw_count"] == 0
    assert "ロングテールKW数" in summary["reasoning"]


def test_none_volume_treated_as_zero_not_a_crash():
    rows = [_row("main", None, is_main=True), _row("lt1", None), _row("lt2", None), _row("lt3", None)]
    summary = summarize_demand(rows, _config())
    assert summary["total_search_volume"] == 0
    assert summary["phase1_result"] == "FAIL"


def test_top_keywords_sorted_descending_and_capped():
    rows = [_row(f"kw{i}", i * 10, is_main=(i == 9)) for i in range(15)]
    summary = summarize_demand(rows, _config(min_longtail_kw_count=1), top_n=5)
    assert len(summary["top_keywords"]) == 5
    assert summary["top_keywords"][0]["keyword"] == "kw14"
    assert summary["top_keywords"][0]["monthly_search_volume"] == 140


def test_dispersion_is_none_with_fewer_than_two_datapoints():
    rows = [_row("main", 500, is_main=True)]
    summary = summarize_demand(rows, _config(min_longtail_kw_count=0))
    assert summary["dispersion"] is None
