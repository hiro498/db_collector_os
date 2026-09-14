"""Pure-function unit tests for the PHASE 13 building blocks: citation
persistence math, Readiness-vs-Reality / opportunity-signal classification,
and URL matching. No DB/crawl involved -- see test_observation_pipeline.py
for the end-to-end rollup."""
from __future__ import annotations

from db_collector_os.competitive_intelligence.ai_search.observation.classification import (
    any_cited,
    classify_organic_aio_cross,
    classify_readiness_vs_reality,
    compute_opportunity_signals,
    organic_band,
)
from db_collector_os.competitive_intelligence.ai_search.observation.config import ObservationConfig
from db_collector_os.competitive_intelligence.ai_search.observation.persistence import (
    citation_frequency,
    persistence_score,
)
from db_collector_os.competitive_intelligence.ai_search.observation.url_matching import normalize_citation_url


# ---- persistence.py ----

def test_citation_frequency_none_when_no_observations():
    assert citation_frequency(0, 0) is None


def test_citation_frequency_basic_ratio():
    assert citation_frequency(4, 2) == 0.5


def test_persistence_score_none_when_no_observations():
    assert persistence_score(0, 0) is None


def test_persistence_score_discounts_low_observation_count():
    """1 observation, cited once (freq=1.0) must score lower than 5
    observations, cited every time (freq=1.0) -- same frequency, different
    confidence."""
    low_confidence = persistence_score(1, 1)
    high_confidence = persistence_score(5, 5)
    assert low_confidence < high_confidence
    assert high_confidence == 100.0


def test_persistence_score_caps_confidence_at_saturation_point():
    assert persistence_score(5, 5) == persistence_score(50, 50) == 100.0


# ---- classification.py ----

def test_organic_band_unknown_when_rank_none():
    assert organic_band(None) == "unknown"


def test_organic_band_thresholds():
    assert organic_band(1) == "top3"
    assert organic_band(3) == "top3"
    assert organic_band(4) == "top10"
    assert organic_band(10) == "top10"
    assert organic_band(11) == "top20"
    assert organic_band(100) == "top100"
    assert organic_band(101) == "outside_top100"


def test_any_cited_true_if_either_surface_cited():
    assert any_cited(True, False) is True
    assert any_cited(False, True) is True
    assert any_cited(True, True) is True


def test_any_cited_false_only_if_both_known_and_neither_cited():
    assert any_cited(False, False) is False


def test_any_cited_none_when_unknown():
    assert any_cited(None, None) is None
    assert any_cited(None, False) is None
    assert any_cited(False, None) is None


def test_classify_readiness_vs_reality_none_when_readiness_unknown():
    assert classify_readiness_vs_reality(None, True) is None


def test_classify_readiness_vs_reality_none_when_cited_unknown():
    assert classify_readiness_vs_reality(80, None) is None


def test_classify_readiness_vs_reality_four_scenarios():
    config = ObservationConfig(high_readiness_threshold=60)
    assert classify_readiness_vs_reality(80, True, config) == "A"  # HIGH_READINESS_CITED
    assert classify_readiness_vs_reality(80, False, config) == "B"  # HIGH_READINESS_NOT_CITED
    assert classify_readiness_vs_reality(30, True, config) == "C"  # LOW_READINESS_CITED
    assert classify_readiness_vs_reality(30, False, config) == "D"  # LOW_READINESS_NOT_CITED


def test_classify_readiness_vs_reality_threshold_boundary_is_inclusive():
    config = ObservationConfig(high_readiness_threshold=60)
    assert classify_readiness_vs_reality(60, True, config) == "A"
    assert classify_readiness_vs_reality(59, True, config) == "C"


def test_classify_organic_aio_cross_none_when_aio_unknown():
    assert classify_organic_aio_cross(3, None) is None


def test_classify_organic_aio_cross_combines_band_and_citation():
    assert classify_organic_aio_cross(2, True) == "organic_top3_aio_cited"
    assert classify_organic_aio_cross(None, False) == "organic_unknown_aio_not_cited"


def test_compute_opportunity_signals_all_none_when_everything_unobserved():
    signals = compute_opportunity_signals(None, None, None, None, None)
    assert all(v is None for v in signals.values())


def test_compute_opportunity_signals_high_readiness_not_cited():
    signals = compute_opportunity_signals(
        readiness_score=80, organic_rank=None, aio_cited=False, ai_mode_cited=False, fanout_visibility_rate=None,
    )
    assert signals["signal_high_readiness_not_cited"] is True


def test_compute_opportunity_signals_low_rank_but_cited():
    signals = compute_opportunity_signals(
        readiness_score=None, organic_rank=50, aio_cited=True, ai_mode_cited=False, fanout_visibility_rate=None,
    )
    assert signals["signal_low_rank_but_cited"] is True


def test_compute_opportunity_signals_high_rank_not_cited():
    signals = compute_opportunity_signals(
        readiness_score=None, organic_rank=5, aio_cited=False, ai_mode_cited=False, fanout_visibility_rate=None,
    )
    assert signals["signal_high_rank_not_cited"] is True


def test_compute_opportunity_signals_fanout_visible_not_root_visible():
    signals = compute_opportunity_signals(
        readiness_score=None, organic_rank=50, aio_cited=None, ai_mode_cited=None, fanout_visibility_rate=0.5,
    )
    assert signals["signal_fanout_visible_not_root_visible"] is True


def test_compute_opportunity_signals_aio_only_ai_mode_only_and_both():
    aio_only = compute_opportunity_signals(None, None, True, False, None)
    ai_mode_only = compute_opportunity_signals(None, None, False, True, None)
    both = compute_opportunity_signals(None, None, True, True, None)
    assert aio_only["signal_aio_only"] is True and aio_only["signal_ai_mode_only"] is False
    assert ai_mode_only["signal_ai_mode_only"] is True and ai_mode_only["signal_aio_only"] is False
    assert both["signal_aio_and_ai_mode"] is True


def test_compute_opportunity_signals_organic_only_requires_all_three_known():
    partial = compute_opportunity_signals(None, 5, True, None, None)
    assert partial["signal_organic_only"] is None
    full = compute_opportunity_signals(None, 5, False, False, None)
    assert full["signal_organic_only"] is True


# ---- url_matching.py ----

def test_normalize_citation_url_matches_crawler_normalization():
    from db_collector_os.competitive_intelligence.url_tools import normalize_url

    url = "https://example.jp/ramen/?utm_source=x#section"
    assert normalize_citation_url(url) == normalize_url(url)


def test_match_page_by_url_returns_none_for_unknown_url(db):
    from db_collector_os.competitive_intelligence.ai_search.observation.url_matching import match_page_by_url

    assert match_page_by_url(db, "no-such-run", "https://competitor.example/x") is None
