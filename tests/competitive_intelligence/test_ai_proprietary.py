from __future__ import annotations

from db_collector_os.competitive_intelligence.ai_search.proprietary import (
    detect_proprietary_signals,
    proprietary_information_score,
    source_traceability_score,
)


def test_firsthand_language_detected():
    hits = detect_proprietary_signals("編集部が実際に42店舗を食べ比べました。")
    assert len(hits["firsthand_hits"]) >= 1


def test_methodology_language_detected():
    hits = detect_proprietary_signals("調査方法はアンケート形式で、調査期間は2026年8月です。")
    assert len(hits["methodology_hits"]) >= 1


def test_proprietary_data_language_detected():
    hits = detect_proprietary_signals("これは編集部調べの独自ランキングです。")
    assert len(hits["proprietary_data_hits"]) >= 1


def test_primary_source_language_detected():
    hits = detect_proprietary_signals("公式発表によると新作は来月発売予定です。")
    assert len(hits["primary_source_hits"]) >= 1


def test_proprietary_metric_language_detected():
    hits = detect_proprietary_signals("独自指数で算出したスコアです。")
    assert len(hits["proprietary_metric_hits"]) >= 1


def test_plain_resummarized_content_has_no_proprietary_signal():
    """A page that only restates generic information (no firsthand/
    methodology/proprietary-data language) must score 0 -- spec section 4:
    "a simple re-summary of other sites' info must not be scored highly"."""
    hits = detect_proprietary_signals("この商品は人気があります。多くの人に選ばれています。")
    assert all(len(v) == 0 for v in hits.values())
    score = proprietary_information_score(0, 0, 0, 0, 0, 0)
    assert score == 0


def test_source_traceability_requires_explicit_sourcing_language():
    assert source_traceability_score(0, 0) == 0
    assert source_traceability_score(1, 1) > 0


def test_proprietary_information_score_capped_at_100():
    score = proprietary_information_score(
        firsthand_count=50, methodology_count=50, proprietary_data_count=50,
        primary_source_count=50, proprietary_metric_count=50, verifiable_fact_count=50,
    )
    assert score == 100


def test_proprietary_information_score_never_negative():
    assert proprietary_information_score(0, 0, 0, 0, 0, 0) == 0
