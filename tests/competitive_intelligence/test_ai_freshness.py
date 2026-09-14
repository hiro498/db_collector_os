from __future__ import annotations

from db_collector_os.competitive_intelligence.ai_search.enums import FreshnessEventType
from db_collector_os.competitive_intelligence.ai_search.freshness import (
    detect_change_events,
    evidence_change_score,
    evidence_freshness_score,
    extract_data_updated_at,
    freshness_timestamp_score,
)


def test_data_updated_at_extracted_from_explicit_label():
    assert extract_data_updated_at("データ更新日: 2026-09-10 現在の情報です。") == "2026-09-10"


def test_data_updated_at_none_when_absent():
    assert extract_data_updated_at("特に更新情報はありません。") is None


def test_arrow_delta_detected_as_review_count_change():
    events = detect_change_events("レビュー数は428件から517件に増加しました。")
    assert any(e.event_type == FreshnessEventType.REVIEW_DELTA for e in events)


def test_arrow_delta_detected_as_ranking_change():
    events = detect_change_events("順位が18位から7位に上昇しました。")
    assert any(e.event_type == FreshnessEventType.RANKING_DELTA for e in events)
    assert events[0].before_value == "18"
    assert events[0].after_value == "7"


def test_ranking_delta_via_arrow_symbol():
    events = detect_change_events("18位→7位にランクアップ。")
    assert len(events) >= 1


def test_price_delta_detected():
    events = detect_change_events("価格は1000円から800円に変更されました。")
    assert any(e.event_type == FreshnessEventType.PRICE_DELTA for e in events)


def test_fake_freshness_date_only_update_scores_zero_change():
    """spec section 7: "2026/9/10更新" alone (a timestamp with no
    demonstrated change) must NOT earn evidence_change_score points."""
    events = detect_change_events("2026年9月10日更新しました。最新情報です。")
    assert events == []
    assert evidence_change_score(events) == 0


def test_meaningful_delta_earns_change_score():
    events = detect_change_events("レビュー数は428件から517件に増加しました。")
    assert evidence_change_score(events) > 0


def test_freshness_timestamp_score_alone_is_capped_low():
    """Even with all three timestamps present, the pure-timestamp
    component must stay a minority contributor -- date alone is weak
    evidence (spec section 7)."""
    score = freshness_timestamp_score("2026-01-01", "2026-06-01", "2026-09-01")
    assert score <= 30


def test_freshness_timestamp_score_zero_when_all_absent():
    assert freshness_timestamp_score(None, None, None) == 0


def test_evidence_freshness_score_dominated_by_change_signal_not_timestamps():
    only_timestamps = evidence_freshness_score(timestamp_score=30, change_score=0)
    with_change = evidence_freshness_score(timestamp_score=30, change_score=100)
    assert with_change > only_timestamps
    assert only_timestamps < 20  # a bare "updated on X" page should rank low


def test_evidence_freshness_score_capped_at_100():
    assert evidence_freshness_score(timestamp_score=100, change_score=100) <= 100
