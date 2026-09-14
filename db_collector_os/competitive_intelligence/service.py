"""Orchestration layer shared by `cli.py` and `web/app.py` (spec section 44:
CORE ENGINE -> DATABASE -> {CLI, Web Dashboard}). Neither entry point talks
to CrawlEngine/repositories directly -- both go through here, so CLI and
Web can never drift in what a given operation actually does.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from ..config import AppConfig
from ..database import Database
from .ai_search import pipeline as ai_search_pipeline
from .ai_search.repository import (
    AiComparisonRepository,
    AiFanoutQueryRepository,
    AiFreshnessEventRepository,
    AiNumericFactRepository,
)
from .crawler import CrawlEngine
from .enums import InputMode
from .exporter import export_all
from .link_analyzer import compute_link_metrics
from .repository.core import CrawlRunRepository, CrawlUrlRepository, DomainRepository
from .repository.keywords import KeywordRepository
from .repository.pages import PageRepository


def detect_input_mode(url: str) -> str:
    """Placeholder AUTO heuristic (spec section 5: "an extensible interface
    for AUTO detection", explicitly not required to be sophisticated in
    P0). A bare domain root is treated as an affiliate/media site to crawl
    in full; any deeper, specific URL is treated as a single advertiser LP.
    Swap this function out (or make it pluggable) when a real classifier
    exists -- nothing else in this package depends on its internals.
    """
    path = urlsplit(url).path
    return InputMode.AFFILIATE_DOMAIN if path in ("", "/") else InputMode.ADVERTISER_LP


def resolve_input_mode(url: str, requested_mode: str) -> str:
    if requested_mode and requested_mode != InputMode.AUTO:
        return requested_mode
    return detect_input_mode(url)


def _db(config: AppConfig) -> Database:
    return Database(config.db_path)


def start_investigation(config: AppConfig, url: str, requested_mode: str = InputMode.AUTO,
                         vertical: str = "general") -> str:
    if requested_mode not in InputMode.ALL:
        raise ValueError(f"unknown mode: {requested_mode}")
    resolved = resolve_input_mode(url, requested_mode)
    db = _db(config)
    engine = CrawlEngine(db, user_agent=config.user_agent)
    if resolved == InputMode.ADVERTISER_LP:
        return engine.start_advertiser_lp(url, requested_mode, vertical)
    return engine.start_affiliate_domain(url, requested_mode, vertical)


def resume(config: AppConfig, crawl_run_id: str) -> str:
    db = _db(config)
    return CrawlEngine(db, user_agent=config.user_agent).resume(crawl_run_id)


def request_stop(config: AppConfig, crawl_run_id: str) -> None:
    db = _db(config)
    CrawlEngine(db, user_agent=config.user_agent).request_stop(crawl_run_id)


def reanalyze(config: AppConfig, crawl_run_id: str) -> None:
    db = _db(config)
    CrawlEngine(db, user_agent=config.user_agent).reanalyze(crawl_run_id)


def recompute_keywords(config: AppConfig, crawl_run_id: str) -> None:
    """"KW再計算" (section 42/45): re-run only keyword scoring finalization
    (no re-parse, no re-classification), for when only scoring weights
    changed."""
    from .keyword.pipeline import finalize_run

    db = _db(config)
    finalize_run(db, crawl_run_id)


def list_investigations(config: AppConfig, limit: int = 100) -> list[dict[str, Any]]:
    db = _db(config)
    return CrawlRunRepository(db).list_recent(limit)


def get_run(config: AppConfig, crawl_run_id: str) -> dict[str, Any] | None:
    db = _db(config)
    return CrawlRunRepository(db).get(crawl_run_id)


def get_status(config: AppConfig, crawl_run_id: str) -> dict[str, Any] | None:
    db = _db(config)
    run = CrawlRunRepository(db).get(crawl_run_id)
    if not run:
        return None
    counts = CrawlUrlRepository(db).count_by_status(crawl_run_id)
    return {"run": run, "crawl_url_status_counts": counts}


def list_crawl_urls(config: AppConfig, crawl_run_id: str, limit: int = 200, offset: int = 0,
                     status: str | None = None) -> list[dict[str, Any]]:
    db = _db(config)
    return CrawlUrlRepository(db).list_all(crawl_run_id, limit=limit, offset=offset, status=status)


def list_pages(config: AppConfig, crawl_run_id: str, limit: int = 200, offset: int = 0,
                page_type: str | None = None, analysis_target: bool | None = None,
                q: str | None = None, indexable: bool | None = None,
                monetization_type: str | None = None, min_score: int | None = None) -> list[dict[str, Any]]:
    db = _db(config)
    return PageRepository(db).list_for_run(
        crawl_run_id, limit=limit, offset=offset, page_type=page_type, analysis_target=analysis_target, q=q,
        indexable=indexable, monetization_type=monetization_type, min_score=min_score,
    )


def list_keywords(config: AppConfig, crawl_run_id: str, **filters: Any) -> list[dict[str, Any]]:
    db = _db(config)
    return KeywordRepository(db).list_keywords_for_run(crawl_run_id, **filters)


def get_keyword_detail(config: AppConfig, crawl_run_id: str, keyword_id: str) -> dict[str, Any] | None:
    db = _db(config)
    return KeywordRepository(db).get_keyword_detail(keyword_id, crawl_run_id)


def get_link_metrics(config: AppConfig, crawl_run_id: str) -> dict[str, dict[str, Any]]:
    """Inbound/outbound counts, orphan flag, TOP distance, and a simple
    PageRank per page_id (spec section 29) -- computed on demand from
    `ci_internal_links` rather than persisted, so a future, more
    sophisticated version needs no schema change."""
    db = _db(config)
    return compute_link_metrics(db, crawl_run_id)


def get_page(config: AppConfig, page_id: str) -> dict[str, Any] | None:
    db = _db(config)
    return PageRepository(db).get(page_id)


def analyze_ai_page(config: AppConfig, page_id: str) -> dict[str, Any]:
    """PHASE 12: first-run AI Search Analysis for one page. Reads only
    already-stored `ci_page_elements` -- makes no network request."""
    db = _db(config)
    return ai_search_pipeline.analyze_ai_page(db, page_id)


def recompute_ai_analysis(config: AppConfig, page_id: str) -> dict[str, Any]:
    """Re-run AI Search Analysis (identical operation to analyze_ai_page --
    see ai_search/pipeline.py's docstring)."""
    db = _db(config)
    return ai_search_pipeline.recompute_ai_analysis(db, page_id)


def get_ai_analysis(config: AppConfig, page_id: str) -> dict[str, Any] | None:
    db = _db(config)
    return ai_search_pipeline.get_ai_analysis(db, page_id)


def get_ai_analysis_evidence(config: AppConfig, page_id: str) -> dict[str, list[dict[str, Any]]]:
    db = _db(config)
    return {
        "numeric_facts": AiNumericFactRepository(db).list_for_page(page_id),
        "comparisons": AiComparisonRepository(db).list_for_page(page_id),
        "freshness_events": AiFreshnessEventRepository(db).list_for_page(page_id),
        "fanout_queries": AiFanoutQueryRepository(db).list_for_page(page_id),
    }


def export_csv(config: AppConfig, crawl_run_id: str, out_dir: str) -> list[str]:
    db = _db(config)
    return export_all(db, crawl_run_id, out_dir)
