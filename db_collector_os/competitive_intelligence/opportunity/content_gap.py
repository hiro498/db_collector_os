"""Content gap analysis (spec section 9): a real structural diff between
our page's and one competitor page's already-extracted content -- every
"missing_*" list here is real text pulled from PHASE 1/12 evidence
(`ci_page_elements`, `ci_ai_numeric_facts`, `ci_ai_comparisons`,
`ci_ai_freshness_events`, `ci_page_keywords`, `ci_internal_links`), never a
guessed/synthetic topic name. `pipeline.py` does the DB reads and passes
plain sets/lists in here so this module stays independently testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Each dimension's share of the overall content_gap_score (sums to 100;
# spec section 21's "no scattered magic numbers" rule -- centralized here).
_DIMENSION_WEIGHTS: dict[str, float] = {
    "keywords": 15.0, "subtopics": 15.0, "entities": 10.0, "questions": 10.0,
    "numeric_facts": 15.0, "comparisons": 15.0, "primary_information": 10.0,
    "freshness": 5.0, "internal_links": 5.0,
}


@dataclass(frozen=True)
class ContentGapResult:
    missing_keywords: list[str]
    missing_subtopics: list[str]
    missing_entities: list[str]
    missing_questions: list[str]
    missing_numeric_facts: list[str]
    missing_comparison_dimensions: list[str]
    missing_primary_information: list[str]
    missing_freshness_evidence: list[str]
    missing_internal_link_topics: list[str]
    content_gap_score: float


def _missing(ours: set[str] | list[str], theirs: set[str] | list[str]) -> list[str]:
    ours_set = set(ours)
    seen: set[str] = set()
    result: list[str] = []
    for item in theirs:
        if item not in ours_set and item not in seen:
            seen.add(item)
            result.append(item)
    return sorted(result)


def _gap_ratio(missing: list[str], theirs: set[str] | list[str]) -> float:
    total = len(set(theirs))
    if total == 0:
        return 0.0
    return min(1.0, len(missing) / total)


def compute_content_gap(
    our_keywords: set[str], competitor_keywords: set[str],
    our_subtopics: set[str], competitor_subtopics: set[str],
    our_entities: set[str], competitor_entities: set[str],
    our_questions: set[str], competitor_questions: set[str],
    our_numeric_facts: list[str], competitor_numeric_facts: list[str],
    our_comparison_structures: set[str], competitor_comparison_structures: set[str],
    our_primary_signals: set[str], competitor_primary_signals: set[str],
    our_freshness_events: list[str], competitor_freshness_events: list[str],
    our_internal_link_topics: set[str], competitor_internal_link_topics: set[str],
) -> ContentGapResult:
    missing = {
        "keywords": _missing(our_keywords, competitor_keywords),
        "subtopics": _missing(our_subtopics, competitor_subtopics),
        "entities": _missing(our_entities, competitor_entities),
        "questions": _missing(our_questions, competitor_questions),
        "numeric_facts": _missing(set(our_numeric_facts), competitor_numeric_facts),
        "comparisons": _missing(our_comparison_structures, competitor_comparison_structures),
        "primary_information": _missing(our_primary_signals, competitor_primary_signals),
        "freshness": _missing(set(our_freshness_events), competitor_freshness_events),
        "internal_links": _missing(our_internal_link_topics, competitor_internal_link_topics),
    }
    theirs = {
        "keywords": competitor_keywords, "subtopics": competitor_subtopics, "entities": competitor_entities,
        "questions": competitor_questions, "numeric_facts": competitor_numeric_facts,
        "comparisons": competitor_comparison_structures, "primary_information": competitor_primary_signals,
        "freshness": competitor_freshness_events, "internal_links": competitor_internal_link_topics,
    }
    score = sum(
        _DIMENSION_WEIGHTS[dim] * _gap_ratio(missing[dim], theirs[dim]) for dim in _DIMENSION_WEIGHTS
    )
    return ContentGapResult(
        missing_keywords=missing["keywords"], missing_subtopics=missing["subtopics"],
        missing_entities=missing["entities"], missing_questions=missing["questions"],
        missing_numeric_facts=missing["numeric_facts"], missing_comparison_dimensions=missing["comparisons"],
        missing_primary_information=missing["primary_information"],
        missing_freshness_evidence=missing["freshness"], missing_internal_link_topics=missing["internal_links"],
        content_gap_score=round(score, 2),
    )
