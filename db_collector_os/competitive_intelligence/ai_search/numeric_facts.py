"""Numeric fact detection (spec sections 5 + 15).

Distinguishes a bare number ("レビュー542件") from a number that is
independently *verifiable and comparative* ("同ジャンル2,843作品中レビュー数
上位2.1%") -- only the latter kind should ever move a score. This module
never scores on raw numeric density; every count it produces is a count of
*classified* facts, and every one of those is written to
``ci_ai_numeric_facts`` with the surrounding text as evidence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .enums import NumericFactType

_NUMBER_RE = re.compile(r"[+\-]?\d[\d,]*\.?\d*")
_RATIO_PERCENTAGE_RE = re.compile(r"\d[\d,]*\.?\d*\s*(?:%|パーセント)")
_RANKING_RE = re.compile(r"(\d+)\s*位(?:\s*/\s*(\d[\d,]*)\s*(?:件|作品|人|店舗?)?中?)?")
_SAMPLE_SIZE_RE = re.compile(
    r"(?:n\s*=\s*\d+"
    r"|対象[はと]?\s*\d[\d,]*\s*(?:件|人|作品|店舗)"
    r"|\d[\d,]*\s*(?:件|人|作品|店舗)\s*(?:を|に)\s*対象"
    r"|回答(?:者|数)\s*\d[\d,]*\s*人)",
    re.IGNORECASE,
)
_DERIVED_MARKERS = ("平均より", "偏差値", "中央値", "上位", "下位", "標準偏差")
_COMPARISON_MARKERS = (
    "同ジャンル", "同カテゴリ", "同シリーズ", "同女優", "同メーカー", "同レーベル",
    "全体の", "業界平均", "他の作品", "平均と比較", "に比べて",
)
_CONTEXT_WINDOW = 20


@dataclass
class NumericFactCandidate:
    fact_type: str
    signal_value: str
    source_text: str
    confidence: float = 0.6


def detect_numeric_facts(text: str) -> list[NumericFactCandidate]:
    if not text:
        return []
    candidates: list[NumericFactCandidate] = []
    consumed: list[tuple[int, int]] = []

    def _mark(start: int, end: int) -> None:
        consumed.append((start, end))

    def _overlaps(start: int, end: int) -> bool:
        return any(start < c_end and end > c_start for c_start, c_end in consumed)

    for m in _RATIO_PERCENTAGE_RE.finditer(text):
        candidates.append(NumericFactCandidate(
            NumericFactType.RATIO_PERCENTAGE, m.group(0), _snippet(text, m.start(), m.end()), 0.8
        ))
        _mark(m.start(), m.end())

    for m in _RANKING_RE.finditer(text):
        candidates.append(NumericFactCandidate(
            NumericFactType.RANKING, m.group(0), _snippet(text, m.start(), m.end()), 0.8
        ))
        _mark(m.start(), m.end())

    for m in _SAMPLE_SIZE_RE.finditer(text):
        candidates.append(NumericFactCandidate(
            NumericFactType.SAMPLE_SIZE, m.group(0), _snippet(text, m.start(), m.end()), 0.8
        ))
        _mark(m.start(), m.end())

    for m in _NUMBER_RE.finditer(text):
        if _overlaps(m.start(), m.end()):
            continue
        window = text[max(0, m.start() - _CONTEXT_WINDOW): m.end() + _CONTEXT_WINDOW]
        if any(marker in window for marker in _COMPARISON_MARKERS):
            fact_type = NumericFactType.COMPARISON
            confidence = 0.75
        elif any(marker in window for marker in _DERIVED_MARKERS):
            fact_type = NumericFactType.DERIVED
            confidence = 0.7
        else:
            fact_type = NumericFactType.NUMERIC
            confidence = 0.4
        candidates.append(NumericFactCandidate(fact_type, m.group(0), window, confidence))

    return candidates


def _snippet(text: str, start: int, end: int) -> str:
    return text[max(0, start - _CONTEXT_WINDOW): end + _CONTEXT_WINDOW]


def summarize(candidates: list[NumericFactCandidate]) -> dict[str, int]:
    counts = {t: 0 for t in (
        NumericFactType.NUMERIC, NumericFactType.DERIVED, NumericFactType.COMPARISON,
        NumericFactType.RATIO_PERCENTAGE, NumericFactType.RANKING, NumericFactType.SAMPLE_SIZE,
    )}
    for c in candidates:
        counts[c.fact_type] += 1
    return {
        "numeric_fact_count": len(candidates),
        "derived_numeric_fact_count": counts[NumericFactType.DERIVED],
        "comparison_numeric_fact_count": counts[NumericFactType.COMPARISON],
        "ratio_percentage_count": counts[NumericFactType.RATIO_PERCENTAGE],
        "ranking_numeric_fact_count": counts[NumericFactType.RANKING],
        "sample_size_count": counts[NumericFactType.SAMPLE_SIZE],
    }


def quality_score(summary: dict[str, int]) -> int:
    """0-100. Weighted toward "strong" (derived/comparison/ranking/ratio)
    facts; plain numeric_fact_count alone contributes nothing -- spec
    section 5 explicitly forbids scoring on numeric density.
    """
    strong = (
        summary["derived_numeric_fact_count"] * 12
        + summary["comparison_numeric_fact_count"] * 15
        + summary["ranking_numeric_fact_count"] * 12
        + summary["ratio_percentage_count"] * 8
        + summary["sample_size_count"] * 10
    )
    return max(0, min(100, strong))
