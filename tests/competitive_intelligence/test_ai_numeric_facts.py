from __future__ import annotations

from db_collector_os.competitive_intelligence.ai_search.enums import NumericFactType
from db_collector_os.competitive_intelligence.ai_search.numeric_facts import (
    detect_numeric_facts,
    quality_score,
    summarize,
)


def test_weak_bare_number_is_classified_plain_numeric():
    facts = detect_numeric_facts("レビュー542件です。")
    assert any(f.fact_type == NumericFactType.NUMERIC and f.signal_value == "542" for f in facts)


def test_comparison_marker_promotes_number_to_comparison_type():
    facts = detect_numeric_facts("同ジャンル2,843作品中で上位に入ります。")
    comparison_facts = [f for f in facts if f.fact_type == NumericFactType.COMPARISON]
    assert any(f.signal_value == "2,843" for f in comparison_facts)


def test_derived_marker_promotes_number_to_derived_type():
    facts = detect_numeric_facts("評価は平均より+0.34高いです。")
    derived = [f for f in facts if f.fact_type == NumericFactType.DERIVED]
    assert len(derived) >= 1


def test_ratio_percentage_detected_as_its_own_type():
    facts = detect_numeric_facts("レビュー数上位2.1%に入ります。")
    assert any(f.fact_type == NumericFactType.RATIO_PERCENTAGE and "2.1" in f.signal_value for f in facts)


def test_ranking_pattern_detected():
    facts = detect_numeric_facts("total 総合7位にランクインしました。")
    assert any(f.fact_type == NumericFactType.RANKING for f in facts)


def test_sample_size_pattern_detected():
    facts = detect_numeric_facts("調査方法はn=42の覆面調査です。")
    assert any(f.fact_type == NumericFactType.SAMPLE_SIZE for f in facts)


def test_sample_size_object_count_pattern_detected():
    facts = detect_numeric_facts("100件を対象にアンケートを実施しました。")
    assert any(f.fact_type == NumericFactType.SAMPLE_SIZE for f in facts)


def test_numeric_false_positive_copyright_year_is_still_just_plain_numeric():
    """A bare year in a copyright line must never be classified as a
    "strong" (derived/comparison/ranking) fact -- spec section 16."""
    facts = detect_numeric_facts("Copyright 2024 All rights reserved.")
    assert all(f.fact_type == NumericFactType.NUMERIC for f in facts)


def test_numeric_false_positive_phone_number_is_plain_numeric():
    facts = detect_numeric_facts("お電話は0120-123-456までどうぞ。")
    assert all(f.fact_type != NumericFactType.COMPARISON and f.fact_type != NumericFactType.DERIVED for f in facts)


def test_no_overlap_between_ranking_and_ratio_matches():
    # "7位" should not also register as a stray plain-numeric "7".
    facts = detect_numeric_facts("7位にランクインしました。")
    numeric_only = [f for f in facts if f.fact_type == NumericFactType.NUMERIC and f.signal_value == "7"]
    assert numeric_only == []


def test_summarize_counts_each_type_independently():
    facts = detect_numeric_facts("同ジャンル100件中、上位5%、n=30で調査しました。")
    summary = summarize(facts)
    assert summary["numeric_fact_count"] == len(facts)
    assert summary["ratio_percentage_count"] >= 1
    assert summary["sample_size_count"] >= 1


def test_quality_score_ignores_plain_numeric_density():
    """Ten bare numbers must score the same (0) as zero numbers -- spec
    section 5 explicitly forbids scoring on raw numeric density."""
    plain_summary = summarize(detect_numeric_facts(" ".join(str(n) for n in range(10))))
    assert quality_score(plain_summary) == 0


def test_quality_score_rewards_strong_facts():
    strong_summary = summarize(detect_numeric_facts("同ジャンル100件中、上位2.1%、7位、平均より+0.3、n=42"))
    assert quality_score(strong_summary) > 0


def test_quality_score_capped_at_100():
    text = " ".join(f"同ジャンル{i}件中上位{i}%" for i in range(50))
    summary = summarize(detect_numeric_facts(text))
    assert quality_score(summary) <= 100
