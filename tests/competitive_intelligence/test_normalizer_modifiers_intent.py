from __future__ import annotations

from db_collector_os.competitive_intelligence.enums import BrandedType, Intent, IntentGroup, KeywordClass
from db_collector_os.competitive_intelligence.keyword import intent as intent_mod
from db_collector_os.competitive_intelligence.keyword import modifiers as modifiers_mod
from db_collector_os.competitive_intelligence.keyword.normalizer import (
    classify_branded,
    classify_keyword_class,
    normalize_keyword,
)


def test_normalize_keyword_folds_fullwidth_to_halfwidth_and_lowercases():
    assert normalize_keyword("ラーメン２０２４ＡＢＣ") == "ラーメン2024abc"


def test_normalize_keyword_strips_whitespace():
    assert normalize_keyword("  渋谷 ラーメン  ") == "渋谷 ラーメン"


def test_classify_branded_detects_known_brand_term():
    assert classify_branded("渋谷ラーメン太郎の店舗一覧", {"ラーメン太郎"}) == BrandedType.MIXED
    assert classify_branded("ラーメン太郎", {"ラーメン太郎"}) == BrandedType.BRANDED
    assert classify_branded("渋谷グルメ", {"ラーメン太郎"}) == BrandedType.NON_BRANDED
    assert classify_branded("渋谷グルメ", set()) == BrandedType.NON_BRANDED


def test_classify_keyword_class_by_token_and_modifier_count():
    assert classify_keyword_class(token_count=1, modifier_count=0) == KeywordClass.HEAD
    assert classify_keyword_class(token_count=2, modifier_count=1) == KeywordClass.MIDDLE
    assert classify_keyword_class(token_count=4, modifier_count=2) == KeywordClass.LONG_TAIL


def test_detect_modifiers_matches_dictionary_terms():
    mods = modifiers_mod.detect_modifiers("渋谷ラーメンおすすめランキング")
    assert "recommend" in mods
    assert "ranking" in mods


def test_detect_modifiers_returns_empty_for_plain_keyword():
    assert modifiers_mod.detect_modifiers("渋谷ラーメン") == []


def test_commercial_score_is_bounded_0_to_100():
    assert modifiers_mod.commercial_score([]) == 0
    high = modifiers_mod.commercial_score(["price", "cheap", "coupon", "campaign", "trial", "comparison"])
    assert 0 <= high <= 100
    assert high == 100  # sum exceeds 100 pre-clamp -- must clamp, not overflow


def test_commercial_score_never_negative_for_informational_only_modifiers():
    assert modifiers_mod.commercial_score(["meaning", "difference"]) == 0


def test_classify_intent_transactional_from_modifier():
    intent, group = intent_mod.classify_intent("ラーメン クーポン", ["coupon"], is_local=False, branded_type="non_branded")
    assert intent == Intent.TRANSACTIONAL
    assert group == IntentGroup.BUY


def test_classify_intent_commercial_investigation_from_modifier():
    intent, group = intent_mod.classify_intent("ラーメン ランキング", ["ranking"], is_local=False, branded_type="non_branded")
    assert intent == Intent.COMMERCIAL_INVESTIGATION
    assert group == IntentGroup.DO


def test_classify_intent_local():
    intent, group = intent_mod.classify_intent("渋谷 ラーメン", [], is_local=True, branded_type="non_branded")
    assert intent == Intent.LOCAL
    assert group == IntentGroup.GO


def test_classify_intent_navigational_for_pure_brand_term():
    intent, group = intent_mod.classify_intent("ラーメン太郎", [], is_local=False, branded_type="branded")
    assert intent == Intent.NAVIGATIONAL
    assert group == IntentGroup.GO


def test_classify_intent_defaults_to_informational():
    intent, group = intent_mod.classify_intent("ラーメンとは", [], is_local=False, branded_type="non_branded")
    assert intent == Intent.INFORMATIONAL
    assert group == IntentGroup.KNOW
