from __future__ import annotations

from db_collector_os.competitive_intelligence.ai_search.enums import FanoutIntentClass
from db_collector_os.competitive_intelligence.ai_search.fanout import (
    PageIntentSignals,
    fanout_content_coverage_score,
    generate_fanout_candidates,
)


def _signals(**overrides) -> PageIntentSignals:
    defaults = dict(modifiers=frozenset(), has_informational=False, is_branded=False, is_local=False)
    defaults.update(overrides)
    return PageIntentSignals(**defaults)


def test_generates_candidates_for_every_intent_class():
    candidates = generate_fanout_candidates("渋谷ラーメン", _signals())
    classes = {c.intent_class for c in candidates}
    assert classes == set(FanoutIntentClass.ALL)


def test_subquery_text_includes_base_keyword():
    candidates = generate_fanout_candidates("渋谷ラーメン", _signals())
    assert all("渋谷ラーメン" in c.subquery_text for c in candidates)


def test_empty_base_keyword_yields_no_candidates():
    assert generate_fanout_candidates("", _signals()) == []


def test_serp_observed_is_never_set_by_this_module():
    """spec section 10: fan-out must never claim a query is actually
    ranked without an external SERP fetch. The dataclass has no
    serp_observed field at all -- the caller (repository) is solely
    responsible for persisting it as NULL."""
    candidates = generate_fanout_candidates("kw", _signals())
    assert not hasattr(candidates[0], "serp_observed")


def test_coverage_reflects_page_modifiers():
    signals = _signals(modifiers=frozenset({"comparison", "ranking"}))
    candidates = generate_fanout_candidates("kw", signals)
    comparison_candidates = [c for c in candidates if c.intent_class == FanoutIntentClass.COMPARISON]
    price_candidates = [c for c in candidates if c.intent_class == FanoutIntentClass.PRICE]
    assert all(c.covered_by_content for c in comparison_candidates)
    assert all(not c.covered_by_content for c in price_candidates)


def test_brand_and_local_coverage_use_dedicated_flags():
    signals = _signals(is_branded=True, is_local=True)
    candidates = generate_fanout_candidates("kw", signals)
    brand = [c for c in candidates if c.intent_class == FanoutIntentClass.BRAND]
    local = [c for c in candidates if c.intent_class == FanoutIntentClass.LOCAL]
    assert all(c.covered_by_content for c in brand)
    assert all(c.covered_by_content for c in local)


def test_fanout_content_coverage_score_zero_when_nothing_covered():
    candidates = generate_fanout_candidates("kw", _signals())
    assert fanout_content_coverage_score(candidates) == 0


def test_fanout_content_coverage_score_full_when_everything_covered():
    signals = _signals(
        modifiers=frozenset({"comparison", "price", "cheap", "review", "reputation", "ranking", "howto", "problem"}),
        has_informational=True, is_branded=True, is_local=True,
    )
    candidates = generate_fanout_candidates("kw", signals)
    assert fanout_content_coverage_score(candidates) == 100


def test_fanout_content_coverage_score_bounded_0_to_100():
    assert 0 <= fanout_content_coverage_score([]) <= 100
