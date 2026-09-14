"""Rolls PHASE 13's external observations up into ``ci_ai_page_visibility``
and compares them against PHASE 12's internal, locally-computed
``ai_citation_readiness_score`` (spec sections 9-11). This is the only
module in the codebase that reads both halves at once -- everywhere else
the internal (``ci_ai_page_analysis``) and external (this package's
``ci_*`` observation tables) stay untouched by each other.

Organic/AIO/AI-Mode observations are recorded per *query*, not per page, so
rolling them up for a page first requires knowing which queries that page
is actually being tracked against. ``_page_queries`` supplies that set from
two existing, already-computed sources: PHASE 12's generated fan-out
subqueries for the page (``ci_ai_fanout_queries.base_keyword``) and the
page's own top-scoring PHASE 1 keywords (``ci_page_keywords``) -- no new
"query" concept is introduced here.
"""

from __future__ import annotations

from typing import Any

from ....database import Database
from .classification import (
    any_cited,
    classify_organic_aio_cross,
    classify_readiness_vs_reality,
    compute_opportunity_signals,
)
from .config import DEFAULT_CONFIG, ObservationConfig
from .persistence import citation_frequency, persistence_score
from .repository import AiModeObservationRepository, AioObservationRepository, PageVisibilityRepository

_MAX_TRACKED_QUERIES = 5


def _readiness_score(db: Database, page_id: str) -> int | None:
    row = db.query_one(
        "SELECT ai_citation_readiness_score FROM ci_ai_page_analysis WHERE page_id=?", (page_id,)
    )
    return row["ai_citation_readiness_score"] if row else None


def _page_queries(db: Database, page_id: str) -> list[str]:
    """Distinct queries this page is tracked against: PHASE 12 fan-out base
    keywords first (they already represent "queries this page should be
    relevant for"), then the page's own top PHASE 1 keywords as a fallback
    for pages that predate fan-out generation."""
    queries: list[str] = []
    for row in db.query(
        "SELECT DISTINCT base_keyword FROM ci_ai_fanout_queries WHERE page_id=?", (page_id,)
    ):
        if row["base_keyword"] not in queries:
            queries.append(row["base_keyword"])
    for row in db.query(
        "SELECT k.keyword FROM ci_page_keywords pk JOIN ci_keywords k ON k.keyword_id = pk.keyword_id "
        "WHERE pk.page_id=? ORDER BY pk.score DESC LIMIT ?",
        (page_id, _MAX_TRACKED_QUERIES),
    ):
        if row["keyword"] not in queries:
            queries.append(row["keyword"])
    return queries[:_MAX_TRACKED_QUERIES]


def _organic_visibility(db: Database, normalized_url: str) -> dict[str, Any]:
    """Best (most recent) organic-SERP sighting of this exact URL, across
    every tracked query -- spec section 5 asks "is this page visible in
    organic search at all", not just for one fixed query."""
    row = db.query_one(
        "SELECT r.result_position, o.observed_at FROM ci_serp_observation_results r "
        "JOIN ci_serp_observations o ON o.serp_observation_id = r.serp_observation_id "
        "WHERE r.normalized_url=? ORDER BY o.observed_at DESC LIMIT 1",
        (normalized_url,),
    )
    if not row:
        return {
            "organic_rank": None, "organic_top3": None, "organic_top10": None,
            "organic_top20": None, "organic_top100": None, "organic_observed_at": None,
        }
    rank = row["result_position"]
    return {
        "organic_rank": rank,
        "organic_top3": int(rank <= 3),
        "organic_top10": int(rank <= 10),
        "organic_top20": int(rank <= 20),
        "organic_top100": int(rank <= 100),
        "organic_observed_at": row["observed_at"],
    }


def _surface_rollup(
    repo: AioObservationRepository | AiModeObservationRepository, id_field: str, queries: list[str],
    normalized_url: str, config: ObservationConfig,
) -> dict[str, Any]:
    """Shared AIO/AI-Mode rollup: both surfaces compute the exact same
    observation-count / citation-count / first-seen / last-seen / frequency
    / persistence shape (spec section 8), just against their own separate
    tables via `repo`."""
    observations: list[dict[str, Any]] = []
    for query in queries:
        observations.extend(
            repo.list_for_query(query, config.default_country, config.default_language, config.default_device)
        )
    if not observations:
        return {
            "cited": None, "citation_position": None, "first_seen": None, "last_seen": None,
            "observation_count": 0, "citation_count": 0, "frequency": None, "persistence": None,
        }
    observations.sort(key=lambda o: o["observed_at"])
    cited_events: list[tuple[str, int | None]] = []
    for obs in observations:
        for citation in repo.citations_for_observation(obs[id_field]):
            if citation["normalized_url"] == normalized_url:
                cited_events.append((obs["observed_at"], citation["citation_position"]))
                break
    observation_count = len(observations)
    citation_count = len(cited_events)
    if citation_count == 0:
        return {
            "cited": False, "citation_position": None, "first_seen": None, "last_seen": None,
            "observation_count": observation_count, "citation_count": 0,
            "frequency": citation_frequency(observation_count, 0),
            "persistence": persistence_score(observation_count, 0),
        }
    cited_events.sort(key=lambda e: e[0])
    return {
        "cited": True,
        "citation_position": cited_events[-1][1],
        "first_seen": cited_events[0][0],
        "last_seen": cited_events[-1][0],
        "observation_count": observation_count,
        "citation_count": citation_count,
        "frequency": citation_frequency(observation_count, citation_count),
        "persistence": persistence_score(observation_count, citation_count),
    }


def _fanout_rollup(db: Database, page_id: str) -> dict[str, Any]:
    fanout_query_ids = [
        row["fanout_query_id"]
        for row in db.query("SELECT fanout_query_id FROM ci_ai_fanout_queries WHERE page_id=?", (page_id,))
    ]
    total = len(fanout_query_ids)
    if total == 0:
        return {"total": 0, "observed": 0, "top10": 0, "top20": 0, "citations": 0, "visibility_rate": None}

    observed = top10 = top20 = citations = visible = 0
    for fanout_query_id in fanout_query_ids:
        latest = db.query_one(
            "SELECT * FROM ci_fanout_observations WHERE fanout_query_id=? ORDER BY observed_at DESC LIMIT 1",
            (fanout_query_id,),
        )
        if not latest:
            continue
        observed += 1
        rank = latest["target_rank"]
        cited = bool(latest["target_cited"])
        if rank is not None and rank <= 10:
            top10 += 1
        if rank is not None and rank <= 20:
            top20 += 1
        if cited:
            citations += 1
        if rank is not None or cited:
            visible += 1

    visibility_rate = None if observed == 0 else round(visible / observed, 4)
    return {"total": total, "observed": observed, "top10": top10, "top20": top20,
             "citations": citations, "visibility_rate": visibility_rate}


def recompute_page_visibility(
    db: Database, page_id: str, config: ObservationConfig = DEFAULT_CONFIG,
) -> dict[str, Any]:
    page = db.query_one("SELECT * FROM ci_pages WHERE page_id=?", (page_id,))
    if not page:
        raise ValueError(f"unknown page_id: {page_id}")
    normalized_url = page["normalized_url"]
    crawl_run_id = page["crawl_run_id"]

    readiness_score = _readiness_score(db, page_id)
    queries = _page_queries(db, page_id)

    organic = _organic_visibility(db, normalized_url)
    aio = _surface_rollup(
        AioObservationRepository(db), "aio_observation_id", queries, normalized_url, config
    )
    ai_mode = _surface_rollup(
        AiModeObservationRepository(db), "ai_mode_observation_id", queries, normalized_url, config
    )
    fanout = _fanout_rollup(db, page_id)

    aio_cited = aio["cited"]
    ai_mode_cited = ai_mode["cited"]
    cited = any_cited(aio_cited, ai_mode_cited)

    fields: dict[str, Any] = {
        **organic,
        "aio_cited": None if aio_cited is None else int(aio_cited),
        "aio_citation_position": aio["citation_position"],
        "aio_first_seen": aio["first_seen"],
        "aio_last_seen": aio["last_seen"],
        "aio_observation_count": aio["observation_count"],
        "aio_citation_count": aio["citation_count"],
        "aio_citation_frequency": aio["frequency"],
        "aio_persistence_score": aio["persistence"],
        "ai_mode_cited": None if ai_mode_cited is None else int(ai_mode_cited),
        "ai_mode_citation_position": ai_mode["citation_position"],
        "ai_mode_first_seen": ai_mode["first_seen"],
        "ai_mode_last_seen": ai_mode["last_seen"],
        "ai_mode_observation_count": ai_mode["observation_count"],
        "ai_mode_citation_count": ai_mode["citation_count"],
        "ai_mode_citation_frequency": ai_mode["frequency"],
        "ai_mode_persistence_score": ai_mode["persistence"],
        "fanout_queries_total": fanout["total"],
        "fanout_queries_observed": fanout["observed"],
        "fanout_top10_count": fanout["top10"],
        "fanout_top20_count": fanout["top20"],
        "fanout_citation_count": fanout["citations"],
        "fanout_visibility_rate": fanout["visibility_rate"],
        "readiness_vs_reality_class": classify_readiness_vs_reality(readiness_score, cited, config),
        "organic_aio_cross_class": classify_organic_aio_cross(organic["organic_rank"], aio_cited),
    }
    signals = compute_opportunity_signals(
        readiness_score, organic["organic_rank"], aio_cited, ai_mode_cited, fanout["visibility_rate"], config,
    )
    fields.update({k: (None if v is None else int(v)) for k, v in signals.items()})

    PageVisibilityRepository(db).upsert(page_id, crawl_run_id, **fields)
    return PageVisibilityRepository(db).get(page_id)


def get_page_visibility(db: Database, page_id: str) -> dict[str, Any] | None:
    return PageVisibilityRepository(db).get(page_id)
