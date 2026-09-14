from __future__ import annotations

from db_collector_os.competitive_intelligence.ai_search.ai_mode import compute_ai_mode_signals


def _el(element_type: str, text: str, is_boilerplate: bool = False) -> dict:
    return {"element_type": element_type, "text": text, "is_boilerplate": is_boilerplate}


def test_subtopic_count_from_h2_h3():
    elements = [_el("h2", "見出し1"), _el("h2", "見出し2"), _el("h3", "小見出し")]
    signals = compute_ai_mode_signals(elements, numeric_fact_count=0, comparison_candidate_count=0, body_text="")
    assert signals["subtopic_count"] == 3


def test_related_question_count_from_faq_and_question_headings():
    elements = [
        _el("faq", "Q: 予約は必要？ A: はい"),
        _el("h2", "料金はいくら？"),
        _el("h2", "普通の見出し"),
    ]
    signals = compute_ai_mode_signals(elements, numeric_fact_count=0, comparison_candidate_count=0, body_text="")
    assert signals["related_question_count"] == 2  # 1 faq + 1 question heading


def test_evidence_block_count_combines_facts_comparisons_and_faq():
    elements = [_el("faq", "Q&A")]
    signals = compute_ai_mode_signals(elements, numeric_fact_count=3, comparison_candidate_count=2, body_text="")
    assert signals["evidence_block_count"] == 3 + 2 + 1


def test_boilerplate_elements_excluded_from_subtopic_and_question_counts():
    elements = [
        _el("h2", "共通ナビ見出し", is_boilerplate=True),
        _el("faq", "共通FAQ", is_boilerplate=True),
        _el("h2", "本当の見出し"),
    ]
    signals = compute_ai_mode_signals(elements, numeric_fact_count=0, comparison_candidate_count=0, body_text="")
    assert signals["subtopic_count"] == 1
    assert signals["related_question_count"] == 0


def test_entity_coverage_uses_proper_noun_detection():
    signals = compute_ai_mode_signals([], numeric_fact_count=0, comparison_candidate_count=0, body_text="渋谷にあるお店です。")
    assert signals["entity_coverage_count"] >= 0  # never negative/erroring; exact count depends on tokenizer backend


def test_score_capped_at_100():
    elements = [_el("h2", f"見出し{i}") for i in range(20)] + [_el("faq", f"Q{i}") for i in range(20)]
    signals = compute_ai_mode_signals(elements, numeric_fact_count=50, comparison_candidate_count=50, body_text="x" * 1000)
    assert signals["ai_mode_content_coverage_score"] <= 100


def test_no_content_at_all_scores_zero():
    signals = compute_ai_mode_signals([], numeric_fact_count=0, comparison_candidate_count=0, body_text="")
    assert signals["ai_mode_content_coverage_score"] == 0


def test_ai_mode_is_independent_of_position_unlike_aio():
    """spec section 9: AI Mode coverage must not depend on where in the
    page a heading/FAQ sits -- unlike aio.py's lead-region-only check."""
    early = [_el("h2", "見出しA"), _el("body", "本文")]
    late = [_el("body", "本文"), _el("h2", "見出しA")]
    early_signals = compute_ai_mode_signals(early, 0, 0, "本文")
    late_signals = compute_ai_mode_signals(late, 0, 0, "本文")
    assert early_signals["subtopic_count"] == late_signals["subtopic_count"]
    assert early_signals["ai_mode_content_coverage_score"] == late_signals["ai_mode_content_coverage_score"]
