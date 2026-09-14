"""AI Mode structure coverage (spec section 9). Deliberately scored as
*coverage* (how many distinct subtopics/questions/entities/evidence
blocks the page addresses), never as a claim that AI Mode will actually
cite the page -- see the module-level warning in
competitive_intelligence/ai_search/__init__.py. Kept entirely separate
from aio.py: AI Mode's own synthesis process draws from many sources
regardless of where in a page information sits, so nothing here rewards
or penalizes based on position the way aio.py's lead-region check does.
"""

from __future__ import annotations

import re

from .tokenizer_utils import proper_noun_count

_QUESTION_HEADING_RE = re.compile(r"[?？]")


def compute_ai_mode_signals(
    elements: list[dict], numeric_fact_count: int, comparison_candidate_count: int, body_text: str,
) -> dict[str, int]:
    non_boilerplate = [e for e in elements if not e.get("is_boilerplate")]
    subtopic_count = sum(1 for e in non_boilerplate if e["element_type"] in ("h2", "h3"))
    faq_count = sum(1 for e in non_boilerplate if e["element_type"] == "faq")
    question_headings = sum(
        1 for e in non_boilerplate
        if e["element_type"] in ("h1", "h2", "h3", "h4") and _QUESTION_HEADING_RE.search(e["text"] or "")
    )
    related_question_count = faq_count + question_headings
    entity_coverage_count = proper_noun_count(body_text)
    evidence_block_count = numeric_fact_count + comparison_candidate_count + faq_count

    score = (
        min(subtopic_count, 6) * 8
        + min(related_question_count, 5) * 8
        + min(entity_coverage_count, 10) * 3
        + min(evidence_block_count, 6) * 5
    )
    return {
        "subtopic_count": subtopic_count,
        "related_question_count": related_question_count,
        "entity_coverage_count": entity_coverage_count,
        "evidence_block_count": evidence_block_count,
        "ai_mode_content_coverage_score": max(0, min(100, score)),
    }
