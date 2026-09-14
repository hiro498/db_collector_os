"""Comparison-information detection (spec section 6). The presence of a
`<table>` tag is never scored directly -- what matters is whether the page
gives AI a *normalized* comparison (the same dimensions, under the same
conditions, across 2+ named entities), and that structure is recognized
from tables, lists, headings, or body prose alike, each with a confidence
that reflects how reliable that source of evidence actually is.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .enums import ComparisonStructureType

_COMPARISON_MARKERS = ("vs", "VS", "対", "比較すると", "それぞれ", "一方", "に対して")
_LIST_DELIMITER_RE = re.compile(r"[:：]")


@dataclass
class ComparisonCandidate:
    structure_type: str
    entity_count: int
    dimension_count: int
    normalized: bool
    same_condition: bool
    source_text: str
    confidence: float = 0.5


def detect_from_table(table_text: str, attrs: dict) -> ComparisonCandidate | None:
    row_count = attrs.get("row_count", 0)
    column_count = attrs.get("column_count", 0)
    if row_count < 2:
        return None  # a single-row "table" compares nothing
    return ComparisonCandidate(
        structure_type=ComparisonStructureType.TABLE,
        entity_count=row_count,
        dimension_count=max(1, column_count),
        normalized=column_count >= 2,
        same_condition=True,  # every row of one table shares the same columns by construction
        source_text=table_text,
        confidence=0.85,
    )


def detect_from_list(list_text: str, attrs: dict) -> ComparisonCandidate | None:
    item_count = attrs.get("item_count", 0)
    if item_count < 2:
        return None
    items = list_text.split(" ||| ")
    dimension_counts = [len(_LIST_DELIMITER_RE.split(i)) - 1 for i in items]
    dimension_count = max(dimension_counts) if dimension_counts else 0
    # A list where every item follows "label: value" is a much stronger,
    # more normalized comparison signal than a plain bulleted list.
    is_structured = dimension_count >= 1 and min(dimension_counts) == dimension_count
    return ComparisonCandidate(
        structure_type=ComparisonStructureType.LIST,
        entity_count=item_count,
        dimension_count=max(1, dimension_count),
        normalized=is_structured,
        same_condition=is_structured,
        source_text=list_text[:200],
        confidence=0.6 if is_structured else 0.35,
    )


def detect_from_prose(text: str, structure_type: str, proper_noun_count: int) -> ComparisonCandidate | None:
    """Body/heading prose: weakest evidence source (no guaranteed
    structure), so confidence never exceeds what a table/list gets."""
    if not text or not any(marker in text for marker in _COMPARISON_MARKERS):
        return None
    return ComparisonCandidate(
        structure_type=structure_type,
        entity_count=max(2, proper_noun_count),
        dimension_count=1,
        normalized=False,
        same_condition=False,
        source_text=text[:200],
        confidence=0.3,
    )


def summarize(candidates: list[ComparisonCandidate]) -> dict[str, int]:
    if not candidates:
        return {
            "comparison_entity_count": 0, "comparison_dimension_count": 0,
            "normalized_comparison_signal": 0, "same_condition_comparison_signal": 0,
            "derived_comparison_metric_count": 0, "comparison_source_traceability": 0,
        }
    best = max(candidates, key=lambda c: c.confidence)
    return {
        "comparison_entity_count": max(c.entity_count for c in candidates),
        "comparison_dimension_count": max(c.dimension_count for c in candidates),
        "normalized_comparison_signal": int(any(c.normalized for c in candidates)),
        "same_condition_comparison_signal": int(any(c.same_condition for c in candidates)),
        "derived_comparison_metric_count": sum(
            1 for c in candidates if c.normalized and c.entity_count >= 2
        ),
        "comparison_source_traceability": int(best.confidence >= 0.6),
    }


def comparison_information_score(summary: dict[str, int]) -> int:
    if summary["comparison_entity_count"] < 2:
        return 0
    score = (
        min(summary["comparison_entity_count"], 10) * 4
        + min(summary["comparison_dimension_count"], 5) * 4
        + summary["normalized_comparison_signal"] * 25
        + summary["same_condition_comparison_signal"] * 20
        + min(summary["derived_comparison_metric_count"], 3) * 5
    )
    return max(0, min(100, score))
