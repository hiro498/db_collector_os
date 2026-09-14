"""Source preference / brand affinity internal proxies (spec section 11).

Whether a domain is an actual Google "Preferred Source" cannot be observed
from this codebase -- `source_affinity_score` and
`external_source_preference_status` stay NULL for that reason (see
pipeline.py). What *can* be measured locally is a handful of proxies that
correlate with editorial trustworthiness -- an identifiable author,
a stated editorial policy, a real about/contact page, citations to
external sources, and topical consistency -- combined here into
`source_transparency_score`, a clearly different, internal-only number.
"""

from __future__ import annotations

_AUTHOR_MARKERS = ("執筆者", "著者", "監修", "編集部", "ライター")
_EDITORIAL_POLICY_MARKERS = ("編集ポリシー", "編集方針", "掲載基準", "編集部について", "運営者情報")


def detect_author_identity_signal(text: str) -> bool:
    return bool(text) and any(marker in text for marker in _AUTHOR_MARKERS)


def detect_editorial_policy_signal(text: str) -> bool:
    return bool(text) and any(marker in text for marker in _EDITORIAL_POLICY_MARKERS)


def source_transparency_score(
    author_signal: bool, editorial_signal: bool, about_page_signal: bool,
    contact_transparency_signal: bool, source_citation_consistency: int,
    repeat_entity_coverage: int, topic_specialization_signal: int,
) -> int:
    score = (
        author_signal * 20 + editorial_signal * 15 + about_page_signal * 15
        + contact_transparency_signal * 15 + min(source_citation_consistency, 5) * 4
        + min(repeat_entity_coverage, 5) * 2 + min(topic_specialization_signal, 100) // 10
    )
    return max(0, min(100, score))
