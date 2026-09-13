"""Internal-link graph metrics (spec section 29).

Inbound/outbound counts, orphan detection, TOP distance, and a simple
PageRank are all computed on demand from `ci_internal_links` rather than
persisted as extra columns on `ci_pages` -- nothing in the P0 schema needs
to change for a future, more sophisticated version of these metrics to
replace this implementation.
"""

from __future__ import annotations

from collections import deque
from typing import Any

from ..database import Database
from .enums import PageType
from .repository.links import InternalLinkRepository

PAGERANK_DAMPING = 0.85
PAGERANK_ITERATIONS = 20


def compute_link_metrics(db: Database, crawl_run_id: str) -> dict[str, dict[str, Any]]:
    repo = InternalLinkRepository(db)
    repo.resolve_targets(crawl_run_id)

    pages = db.query("SELECT page_id, page_type FROM ci_pages WHERE crawl_run_id=?", (crawl_run_id,))
    page_ids = [p["page_id"] for p in pages]
    inbound = repo.inbound_count_by_page(crawl_run_id)
    outbound = repo.outbound_count_by_page(crawl_run_id)

    adjacency: dict[str, list[str]] = {pid: [] for pid in page_ids}
    for link in repo.list_for_run(crawl_run_id):
        if link["target_page_id"]:
            adjacency.setdefault(link["source_page_id"], []).append(link["target_page_id"])

    top_pages = [p["page_id"] for p in pages if p["page_type"] == PageType.TOP]
    distances = _bfs_distances(adjacency, top_pages, page_ids)
    pagerank = _simple_pagerank(adjacency, page_ids)

    return {
        pid: {
            "inbound_count": inbound.get(pid, 0),
            "outbound_count": outbound.get(pid, 0),
            "is_orphan": inbound.get(pid, 0) == 0 and pid not in top_pages,
            "top_distance": distances.get(pid),
            "pagerank": pagerank.get(pid, 0.0),
        }
        for pid in page_ids
    }


def _bfs_distances(adjacency: dict[str, list[str]], sources: list[str], all_pages: list[str]) -> dict[str, int]:
    distances: dict[str, int] = {s: 0 for s in sources}
    queue = deque(sources)
    while queue:
        current = queue.popleft()
        for neighbor in adjacency.get(current, []):
            if neighbor not in distances:
                distances[neighbor] = distances[current] + 1
                queue.append(neighbor)
    return distances


def _simple_pagerank(adjacency: dict[str, list[str]], page_ids: list[str]) -> dict[str, float]:
    n = len(page_ids)
    if n == 0:
        return {}
    rank = {pid: 1.0 / n for pid in page_ids}
    for _ in range(PAGERANK_ITERATIONS):
        dangling_mass = sum(rank[pid] for pid in page_ids if not adjacency.get(pid))
        new_rank = {pid: (1 - PAGERANK_DAMPING) / n + PAGERANK_DAMPING * dangling_mass / n for pid in page_ids}
        for pid in page_ids:
            targets = adjacency.get(pid) or []
            if not targets:
                continue
            share = PAGERANK_DAMPING * rank[pid] / len(targets)
            for target in targets:
                if target in new_rank:
                    new_rank[target] += share
        rank = new_rank
    return rank
