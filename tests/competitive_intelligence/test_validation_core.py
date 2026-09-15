"""Pure-function tests for the PHASE 15 building blocks: clustering, noise
detection, machine quality classification, money-keyword classification,
intent rollup, content map, and blue-ocean candidate flagging. No DB/crawl
involved -- see test_validation_pipeline.py for end-to-end coverage.
"""
from __future__ import annotations

from db_collector_os.competitive_intelligence.validation.blue_ocean import evaluate_blue_ocean_candidate
from db_collector_os.competitive_intelligence.validation.clustering import cluster_keywords
from db_collector_os.competitive_intelligence.validation.content_map import build_content_map
from db_collector_os.competitive_intelligence.validation.enums import AuditClass, BlueOceanCandidateStatus, MoneyKeywordClass
from db_collector_os.competitive_intelligence.validation.intent_rollup import rollup_intent
from db_collector_os.competitive_intelligence.validation.money_keyword import classify_money_keyword, money_signals
from db_collector_os.competitive_intelligence.validation.noise import detect_noise, detect_unnatural_ngram
from db_collector_os.competitive_intelligence.validation.quality import compute_audit_class_auto


# ---- clustering.py ----

def test_cluster_order_independent_japanese_word_order():
    result = cluster_keywords(["AV おすすめ", "おすすめ AV"])
    assert result["AV おすすめ"] == result["おすすめ AV"]


def test_cluster_does_not_merge_on_single_shared_word():
    """spec section 9: don't crudely collapse keywords that merely share
    one common word."""
    result = cluster_keywords(["AV おすすめ", "AV 比較"])
    assert result["AV おすすめ"] != result["AV 比較"]


def test_cluster_id_is_deterministic_lexicographic_min():
    result = cluster_keywords(["おすすめ AV", "AV おすすめ"])
    assert result["AV おすすめ"] == "AV おすすめ"  # lexicographically smaller of the two


def test_cluster_original_text_preserved():
    """Clustering only labels -- it must never alter/merge original text."""
    keywords = ["AV おすすめ", "おすすめ AV", "独立キーワード"]
    result = cluster_keywords(keywords)
    assert set(result.keys()) == set(keywords)


def test_cluster_empty_list():
    assert cluster_keywords([]) == {}


# ---- noise.py ----

def test_detect_noise_boilerplate_terms():
    assert detect_noise("利用規約について")[0] is True
    assert detect_noise("お問い合わせフォーム")[0] is True
    assert detect_noise("プライバシーポリシー")[0] is True


def test_detect_noise_generic_scaffolding_exact_match_only():
    assert detect_noise("サイト")[0] is True
    assert detect_noise("比較サイト")[0] is False, "サイト as part of a compound must not be flagged"


def test_detect_noise_single_kanji_is_not_noise():
    assert detect_noise("枕")[0] is False


def test_detect_noise_single_hiragana_is_noise():
    assert detect_noise("し")[0] is True


def test_detect_noise_legitimate_keyword_is_clean():
    is_noise, reason = detect_noise("睡眠グッズ")
    assert is_noise is False
    assert reason is None


def test_detect_unnatural_ngram_verb_fragment():
    others = {"解説", "睡眠グッズ"}
    assert detect_unnatural_ngram("解説し", others)[0] is True


def test_detect_unnatural_ngram_no_match_without_stem_present():
    others = {"睡眠グッズ"}
    is_noise, _ = detect_unnatural_ngram("解説し", others)
    assert is_noise is False


def test_detect_unnatural_ngram_legitimate_word_ending_in_continuative_char_untouched():
    # "おかし" (sweets) ends in "し" but has no shorter "おか" sibling candidate.
    assert detect_unnatural_ngram("おかし", set())[0] is False


# ---- quality.py ----

def test_audit_class_auto_noise_is_always_d():
    assert compute_audit_class_auto(95, is_noise=True) == AuditClass.D


def test_audit_class_auto_high_score_is_a():
    assert compute_audit_class_auto(85, is_noise=False) == AuditClass.A
    assert compute_audit_class_auto(65, is_noise=False) == AuditClass.A


def test_audit_class_auto_single_word_needs_higher_bar_than_compound():
    # A score that clears the compound "related" bar but not the (higher)
    # single-word one: the multi-word phrase becomes B, the single word stays C.
    assert compute_audit_class_auto(32, is_noise=False, token_count=2) == AuditClass.B
    assert compute_audit_class_auto(32, is_noise=False, token_count=1) == AuditClass.C
    assert compute_audit_class_auto(20, is_noise=False, token_count=1) == AuditClass.C


def test_audit_class_auto_very_low_score_is_c_or_d():
    assert compute_audit_class_auto(10, is_noise=False) == AuditClass.D


# ---- money_keyword.py ----

def test_classify_money_keyword_thresholds():
    assert classify_money_keyword(70) == MoneyKeywordClass.HIGH
    assert classify_money_keyword(40) == MoneyKeywordClass.MEDIUM
    assert classify_money_keyword(10) == MoneyKeywordClass.LOW


def test_classify_money_keyword_none_stays_none():
    assert classify_money_keyword(None) is None


def test_money_signals_from_modifiers():
    signals = money_signals({"price", "comparison", "ranking"})
    assert signals["transactional_signal"] is True
    assert signals["comparison_signal"] is True
    assert signals["ranking_signal"] is True
    assert signals["review_signal"] is False


# ---- intent_rollup.py ----

def test_rollup_intent_empty():
    assert rollup_intent([]) == (None, [], "LOW")


def test_rollup_intent_unanimous_is_high_confidence():
    primary, secondary, confidence = rollup_intent(["commercial_investigation", "commercial_investigation"])
    assert primary == "commercial_investigation"
    assert secondary == []
    assert confidence == "HIGH"


def test_rollup_intent_mixed_lists_secondary():
    primary, secondary, confidence = rollup_intent(["informational", "informational", "commercial_investigation"])
    assert primary == "informational"
    assert secondary == ["commercial_investigation"]


# ---- content_map.py ----

def test_build_content_map_filters_by_keyword_class():
    summaries = [
        {"normalized_keyword": "kw1", "keyword": "kw1", "pages_count": 3,
         "page_type_counts": {"article": 2, "ranking": 1}},
        {"normalized_keyword": "kw2", "keyword": "kw2", "pages_count": 1, "page_type_counts": {"article": 1}},
    ]
    keyword_classes = {"kw1": "head", "kw2": "long_tail"}
    money_classes = {"kw1": "HIGH", "kw2": "LOW"}
    result = build_content_map(summaries, keyword_classes, money_classes, {"kw1": 1})
    assert len(result) == 1
    assert result[0]["topic"] == "kw1"
    assert result[0]["article_count"] == 2
    assert result[0]["ranking_count"] == 1
    assert result[0]["commercial_keyword_count"] == 1


def test_build_content_map_sorted_by_page_count_desc():
    summaries = [
        {"normalized_keyword": "small", "keyword": "small", "pages_count": 1, "page_type_counts": {}},
        {"normalized_keyword": "big", "keyword": "big", "pages_count": 10, "page_type_counts": {}},
    ]
    keyword_classes = {"small": "head", "big": "head"}
    result = build_content_map(summaries, keyword_classes, {}, {})
    assert result[0]["topic"] == "big"


# ---- blue_ocean.py ----

def test_blue_ocean_insufficient_data_without_demand_observation():
    candidate, status = evaluate_blue_ocean_candidate(80, 50, 50, 20, demand_observed=False, competitor_count=3)
    assert candidate is None
    assert status == BlueOceanCandidateStatus.INSUFFICIENT_DATA


def test_blue_ocean_insufficient_data_without_opportunity_score():
    candidate, status = evaluate_blue_ocean_candidate(None, 50, 50, 20, demand_observed=True, competitor_count=3)
    assert candidate is None
    assert status == BlueOceanCandidateStatus.INSUFFICIENT_DATA


def test_blue_ocean_never_confirmed_from_unknown_search_volume():
    """spec section 20's explicit prohibition."""
    candidate, status = evaluate_blue_ocean_candidate(95, 90, 90, 5, demand_observed=False, competitor_count=None)
    assert candidate is None
    assert status == BlueOceanCandidateStatus.INSUFFICIENT_DATA


def test_blue_ocean_positive_candidate():
    candidate, status = evaluate_blue_ocean_candidate(80, 50, 50, 20, demand_observed=True, competitor_count=3)
    assert candidate is True
    assert status == BlueOceanCandidateStatus.OK


def test_blue_ocean_negative_when_competitor_proprietary_strong():
    candidate, status = evaluate_blue_ocean_candidate(80, 50, 50, 90, demand_observed=True, competitor_count=3)
    assert candidate is False
    assert status == BlueOceanCandidateStatus.OK
