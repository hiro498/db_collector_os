"""Keyword cluster deduplication (spec section 9). Deliberately
conservative: two keywords only join the same cluster when their
tokenized *content-word* sets are highly similar (Jaccard >= threshold),
which is order-independent -- so "AV おすすめ" and "おすすめ AV" correctly
cluster -- without merging keywords that only share one common word (e.g.
"AV おすすめ" and "AV 比較" do NOT cluster). Clustering only *labels*
likely-duplicate candidates with a shared `cluster_id`; it never merges
their scores/counts, and every keyword's original text is preserved
unchanged. Reuses PHASE 1's own tokenizer -- no new NLP model.
"""

from __future__ import annotations

from ..keyword.tokenizer import get_default_tokenizer
from .config import CLUSTER_JACCARD_THRESHOLD


def _token_set(text: str) -> frozenset[str]:
    tokenizer = get_default_tokenizer()
    return frozenset(m.surface for m in tokenizer.tokenize(text) if m.is_content)


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class _UnionFind:
    def __init__(self, items: list[str]):
        self._parent = {item: item for item in items}

    def find(self, item: str) -> str:
        while self._parent[item] != item:
            self._parent[item] = self._parent[self._parent[item]]
            item = self._parent[item]
        return item

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[ra] = rb


def cluster_keywords(
    normalized_keywords: list[str], threshold: float = CLUSTER_JACCARD_THRESHOLD,
) -> dict[str, str]:
    """Returns {normalized_keyword: cluster_id}. cluster_id is the
    lexicographically-smallest normalized_keyword in that cluster (stable,
    deterministic, and never a fabricated label)."""
    unique = list(dict.fromkeys(normalized_keywords))
    token_sets = {kw: _token_set(kw) for kw in unique}
    uf = _UnionFind(unique)

    for i, kw_a in enumerate(unique):
        for kw_b in unique[i + 1:]:
            if _jaccard(token_sets[kw_a], token_sets[kw_b]) >= threshold:
                uf.union(kw_a, kw_b)

    members_by_root: dict[str, list[str]] = {}
    for kw in unique:
        members_by_root.setdefault(uf.find(kw), []).append(kw)

    assignment: dict[str, str] = {}
    for members in members_by_root.values():
        cluster_id = min(members)
        for kw in members:
            assignment[kw] = cluster_id
    return assignment
