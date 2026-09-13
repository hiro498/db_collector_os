"""Keyword clustering -- P0 baseline only (spec section 46 defers "KW
Cluster高度化" to a later phase). Groups keywords within one crawl_run that
share the same trailing content morpheme (e.g. "渋谷ラーメン" / "新宿ラーメン"
both anchor on "ラーメン"), which is a cheap, explainable proxy for shared
search topic. Singleton groups (no other keyword shares the anchor) are
left unclustered rather than forced into a group of one.
"""

from __future__ import annotations

from collections import defaultdict

from .tokenizer import Tokenizer


def anchor_token(keyword_text: str, tokenizer: Tokenizer) -> str | None:
    morphemes = [m for m in tokenizer.tokenize(keyword_text) if m.is_content]
    if not morphemes:
        return None
    return morphemes[-1].normalized or morphemes[-1].surface


def build_clusters(keywords: list[dict], tokenizer: Tokenizer) -> dict[str, list[str]]:
    """`keywords` is a list of {"keyword_id": ..., "keyword": ...} rows.
    Returns {anchor_token: [keyword_id, ...]} for anchors shared by 2+ keywords.
    """
    groups: dict[str, list[str]] = defaultdict(list)
    for row in keywords:
        anchor = anchor_token(row["keyword"], tokenizer)
        if anchor:
            groups[anchor].append(row["keyword_id"])
    return {anchor: ids for anchor, ids in groups.items() if len(ids) >= 2}
