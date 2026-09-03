from __future__ import annotations

from db_collector_os.viability.competition_analysis import (
    classify_page_type,
    classify_site_type,
    classify_title_match,
    score_keyword_competition,
    summarize_theme_competition,
)
from db_collector_os.viability.config import ViabilityConfig


def _config():
    return ViabilityConfig(
        competition_classification={
            "results_considered": 5,
            "strong_min_score": 60,
            "medium_min_score": 32,
            "site_type_weight": {
                "major_corp": 80, "major_ec": 80, "expert_media": 65, "portal": 55,
                "specialty_store": 30, "small_business": 18, "personal": 10, "unknown": 35,
            },
            "page_type_adjustment": {"listing": 10, "product": 4, "article": 0},
            "db_type_page_bonus": 20,
            "title_exact_match_bonus": 12,
            "title_partial_match_bonus": 4,
            "intent_unsatisfied_relief": 25,
        }
    )


def test_classify_site_type_known_major_ec():
    assert classify_site_type("rakuten.co.jp", "some title") == "major_ec"


def test_classify_site_type_unknown_default():
    assert classify_site_type("random-blog.example", "some title") == "unknown"


def test_classify_page_type_listing_vs_product_vs_article():
    assert classify_page_type("https://x.example/category/rings", "指輪一覧") == "listing"
    assert classify_page_type("https://x.example/item/123", "指輪") == "product"
    assert classify_page_type("https://x.example/blog/post", "指輪について") == "article"


def test_classify_title_match_exact_partial_none():
    assert classify_title_match("指輪 オーダーメイド 特集", "指輪 オーダーメイド") == "exact"
    assert classify_title_match("指輪の選び方", "指輪 オーダーメイド") == "partial"
    assert classify_title_match("ネックレスの選び方", "指輪 オーダーメイド") == "none"
    assert classify_title_match(None, "指輪") == "none"


def test_empty_results_are_weak_and_opportunity_flagged():
    scored = score_keyword_competition("kw", [], _config())
    assert scored["strength"] == "WEAK"
    assert scored["strength_score"] == 0.0


def test_major_ec_with_matching_db_page_is_strong():
    results = [
        {
            "rank": 1, "title": "指輪 オーダーメイド 通販", "url": "https://rakuten.co.jp/category/ring",
            "domain": "rakuten.co.jp", "site_type": "major_ec", "page_type": "listing",
            "db_type_page": True, "intent_satisfied": True, "title_match": "exact",
        }
    ]
    scored = score_keyword_competition("指輪 オーダーメイド", results, _config())
    assert scored["strength"] == "STRONG"
    assert scored["db_type_page_present"] is True


def test_personal_blog_articles_only_is_weak_and_opportunity_flagged():
    results = [
        {
            "rank": 1, "title": "指輪の選び方ブログ", "url": "https://blog.example/ring",
            "domain": "blog.example", "site_type": "personal", "page_type": "article",
            "db_type_page": False, "intent_satisfied": False, "title_match": "partial",
        }
    ]
    scored = score_keyword_competition("指輪 オーダーメイド", results, _config())
    assert scored["strength"] == "WEAK"
    assert scored["intent_satisfied"] is False


def test_heuristic_fallback_used_when_overrides_absent():
    results = [{"rank": 1, "title": "指輪 オーダーメイド 一覧", "url": "https://rakuten.co.jp/category/ring", "domain": "rakuten.co.jp"}]
    scored = score_keyword_competition("指輪 オーダーメイド", results, _config())
    # major_ec (known domain) + listing (URL/title hint) + exact title -> STRONG
    assert scored["strength"] == "STRONG"


def test_summarize_theme_competition_ratios_and_winnable_demand():
    rows = [
        {"candidate_id": "c1", "strength": "WEAK"},
        {"candidate_id": "c2", "strength": "MEDIUM"},
        {"candidate_id": "c3", "strength": "STRONG"},
        {"candidate_id": "c4", "strength": "WEAK"},
    ]
    volumes = {"c1": 100, "c2": 50, "c3": 30, "c4": 20}
    summary = summarize_theme_competition(rows, volumes)
    assert summary["weak_ratio"] == 0.5
    assert summary["medium_ratio"] == 0.25
    assert summary["strong_ratio"] == 0.25
    assert summary["winnable_demand"] == 100 + 50 + 20
    assert summary["unwinnable_demand"] == 30


def test_summarize_theme_competition_empty():
    summary = summarize_theme_competition([], {})
    assert summary["weak_ratio"] is None
    assert summary["winnable_demand"] == 0
