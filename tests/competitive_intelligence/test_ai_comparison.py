from __future__ import annotations

from db_collector_os.competitive_intelligence.ai_search.comparison import (
    comparison_information_score,
    detect_from_list,
    detect_from_prose,
    detect_from_table,
    summarize,
)


def test_table_with_2plus_rows_is_a_comparison():
    candidate = detect_from_table("店名 / 評価 / 価格", {"row_count": 3, "column_count": 3})
    assert candidate is not None
    assert candidate.entity_count == 3
    assert candidate.dimension_count == 3
    assert candidate.normalized is True
    assert candidate.same_condition is True


def test_single_row_table_is_not_a_comparison():
    """A `<table>` used purely for layout (one row) compares nothing --
    spec section 6: table presence alone must not be scored."""
    candidate = detect_from_table("店名 太郎", {"row_count": 1, "column_count": 2})
    assert candidate is None


def test_structured_list_without_any_table_is_detected():
    """spec section 6: comparison structure must be recognizable outside
    of <table> -- a "label: value" list is a normalized comparison."""
    list_text = "店A: 4.5点 ||| 店B: 4.2点 ||| 店C: 4.0点"
    candidate = detect_from_list(list_text, {"item_count": 3})
    assert candidate is not None
    assert candidate.entity_count == 3
    assert candidate.normalized is True


def test_unstructured_list_scores_lower_confidence_than_structured_list():
    unstructured = detect_from_list("ラーメン ||| 餃子 ||| チャーハン", {"item_count": 3})
    structured = detect_from_list("店A: 4.5点 ||| 店B: 4.2点", {"item_count": 2})
    assert unstructured.normalized is False
    assert unstructured.confidence < structured.confidence


def test_single_item_list_is_not_a_comparison():
    assert detect_from_list("店A: 4.5点", {"item_count": 1}) is None


def test_prose_comparison_detected_via_marker_word():
    candidate = detect_from_prose("A社 vs B社を比較すると、A社の方が安いです。", "body", proper_noun_count=2)
    assert candidate is not None
    assert candidate.confidence < 0.5  # prose is the weakest evidence source


def test_prose_without_comparison_marker_is_not_detected():
    assert detect_from_prose("今日はいい天気です。", "body", proper_noun_count=0) is None


def test_table_comparison_has_higher_confidence_than_prose_comparison():
    table = detect_from_table("A / B / C", {"row_count": 2, "column_count": 3})
    prose = detect_from_prose("Aと比較すると", "body", proper_noun_count=1)
    assert table.confidence > prose.confidence


def test_comparison_information_score_zero_without_2plus_entities():
    assert comparison_information_score(summarize([])) == 0


def test_comparison_information_score_capped_at_100():
    candidate = detect_from_table("x", {"row_count": 50, "column_count": 20})
    score = comparison_information_score(summarize([candidate]))
    assert score <= 100
