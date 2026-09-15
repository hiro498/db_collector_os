"""Site Content Map (spec section 14). Reuses PHASE 1's own
`keyword_class` ('head'/'middle'/'long_tail') to pick topic-level
keywords, and this package's own site-wide keyword aggregation
(page-type breakdown, pages_count) to describe how much of the site each
topic covers -- no new topic-modeling step of any kind.
"""

from __future__ import annotations

from typing import Any

_TOPIC_KEYWORD_CLASSES = ("head", "middle")


def build_content_map(
    summaries: list[dict[str, Any]], keyword_classes: dict[str, str], money_classes: dict[str, str | None],
    cluster_sizes: dict[str, int],
) -> list[dict[str, Any]]:
    topics = []
    for s in summaries:
        normalized = s["normalized_keyword"]
        if keyword_classes.get(normalized) not in _TOPIC_KEYWORD_CLASSES:
            continue
        counts = s["page_type_counts"]
        topics.append({
            "topic": s["keyword"],
            "keyword_count": cluster_sizes.get(normalized, 1),
            "page_count": s["pages_count"],
            "article_count": counts.get("article", 0),
            "category_count": counts.get("category", 0) + counts.get("tag", 0),
            "ranking_count": counts.get("ranking", 0),
            "comparison_count": counts.get("comparison", 0),
            "commercial_keyword_count": 1 if money_classes.get(normalized) in ("HIGH", "MEDIUM") else 0,
        })
    return sorted(topics, key=lambda t: (t["page_count"], t["keyword_count"]), reverse=True)
