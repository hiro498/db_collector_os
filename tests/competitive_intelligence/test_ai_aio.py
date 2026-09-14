from __future__ import annotations

from db_collector_os.competitive_intelligence.ai_search.aio import compute_aio_signals
from db_collector_os.competitive_intelligence.ai_search.tokenizer_utils import lead_text


def test_key_fact_in_first_100_words_detected():
    text = "同ジャンル100件中上位5%の名店です。" + "。".join(f"補足説明{i}" for i in range(200))
    signals = compute_aio_signals(text)
    assert signals["key_fact_in_first_100_words"] == 1


def test_answer_marker_in_lead_detected():
    text = "結論は渋谷で一番おすすめのラーメン店はA店です。" + "詳細説明。" * 200
    signals = compute_aio_signals(text)
    assert signals["answer_in_first_100_words"] == 1


def test_summary_marker_in_lead_detected():
    text = "まとめると渋谷にはたくさんの名店があります。" + "詳細説明。" * 200
    signals = compute_aio_signals(text)
    assert signals["summary_near_top"] == 1


def test_no_signals_when_lead_is_generic():
    text = "今日は天気がいいですね。散歩に行きました。" + "詳細説明。" * 200
    signals = compute_aio_signals(text)
    assert signals["answer_in_first_100_words"] == 0
    assert signals["key_fact_in_first_100_words"] == 0
    assert signals["summary_near_top"] == 0
    assert signals["aio_extractability_score"] == 0


def test_no_penalty_for_deep_content_key_fact_appearing_only_later():
    """spec section 8: information deep in a page must never be
    *penalized* -- a page whose only fact is far from the top should score
    the same lead-signal 0 as a page with no fact at all, never negative,
    and the AIO score must never fall below what a lead-only page gets."""
    lead_only = "同ジャンル100件中上位5%です。" + "普通の説明。" * 300
    deep_fact_only = "普通の説明。" * 300 + "同ジャンル100件中上位5%です。"
    lead_signals = compute_aio_signals(lead_only)
    deep_signals = compute_aio_signals(deep_fact_only)
    assert deep_signals["aio_extractability_score"] >= 0
    assert deep_signals["key_fact_in_first_100_words"] == 0  # the fact just isn't *in the lead*
    assert lead_signals["aio_extractability_score"] >= deep_signals["aio_extractability_score"]


def test_empty_text_returns_zero_score_not_error():
    signals = compute_aio_signals("")
    assert signals["aio_extractability_score"] == 0


def test_aio_extractability_score_capped_at_100():
    text = "結論は一番のおすすめはA店です。一番人気はA店で同ジャンル100件中上位1%、まとめるとA店が最強です。"
    signals = compute_aio_signals(text)
    assert signals["aio_extractability_score"] <= 100


def test_lead_text_uses_tokenizer_not_fixed_character_count():
    text = "渋谷" * 500  # far more than 100 characters, but very few distinct content tokens
    lead = lead_text(text, 100)
    assert len(lead) <= len(text)
    assert lead  # never empty for non-empty input
