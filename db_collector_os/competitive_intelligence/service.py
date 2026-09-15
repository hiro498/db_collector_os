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
from .ai_search.observation.config import DEFAULT_CONFIG as OBSERVATION_CONFIG
from .ai_search.observation.importer import import_observation_file
from .ai_search.observation.pipeline import get_page_visibility as _get_page_visibility
from .ai_search.observation.pipeline import recompute_page_visibility as _recompute_page_visibility
from .ai_search.observation.providers import (
    NullAioObservationProvider,
    NullAiModeObservationProvider,
    NullFanoutObservationProvider,
    NullOrganicSerpProvider,
)
from .ai_search.observation.repository import ImportBatchRepository
from .opportunity import pipeline as opportunity_pipeline
from .opportunity.demand_importer import import_keyword_metrics_file
from .opportunity.repository import ContentGapRepository, OpportunityRepository
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


def get_page_visibility(config: AppConfig, page_id: str) -> dict[str, Any] | None:
    """PHASE 13: reads the stored Readiness-vs-Reality rollup for one page
    (or None if `recompute_page_visibility` has never run for it -- no
    on-the-fly computation here, so a caller reading `None` never confuses
    "not yet computed" with "computed and found nothing")."""
    db = _db(config)
    return _get_page_visibility(db, page_id)


def recompute_page_visibility(config: AppConfig, page_id: str) -> dict[str, Any]:
    """Rolls up whatever external observations are currently stored (via
    `import_observation`) against PHASE 12's internal readiness score for
    one page. Makes no network request itself."""
    db = _db(config)
    return _recompute_page_visibility(db, page_id)


def import_observation(
    config: AppConfig, file_path: str, observation_type: str, provider: str | None = None,
) -> dict[str, Any]:
    """Offline import of externally-gathered SERP/AIO/AI-Mode/fan-out/GSC
    data (spec: the primary path to real observation data in this
    environment -- see observation/__init__.py)."""
    db = _db(config)
    return import_observation_file(db, file_path, observation_type, provider=provider)


def list_observation_import_batches(config: AppConfig, limit: int = 50) -> list[dict[str, Any]]:
    db = _db(config)
    return ImportBatchRepository(db).list_recent(limit=limit)


def observation_status(config: AppConfig) -> dict[str, Any]:
    """High-level counts of what has actually been imported/computed so far
    (spec: `ci observation status`) -- every count reflects real stored
    rows, never an estimate."""
    db = _db(config)

    def _count(table: str) -> int:
        row = db.query_one(f"SELECT COUNT(*) AS n FROM {table}")
        return row["n"] if row else 0

    return {
        "serp_observations": _count("ci_serp_observations"),
        "aio_observations": _count("ci_aio_observations"),
        "ai_mode_observations": _count("ci_ai_mode_observations"),
        "fanout_observations": _count("ci_fanout_observations"),
        "gsc_observations": _count("ci_gsc_observations"),
        "pages_with_visibility_computed": _count("ci_ai_page_visibility"),
        "import_batches": _count("ci_observation_import_batches"),
    }


_OBSERVE_PROVIDERS: dict[str, Any] = {
    "organic": NullOrganicSerpProvider(),
    "aio": NullAioObservationProvider(),
    "ai-mode": NullAiModeObservationProvider(),
    "fanout": NullFanoutObservationProvider(),
}


def observe(
    config: AppConfig, surface: str, query: str, country: str | None = None,
    language: str | None = None, device: str | None = None,
) -> dict[str, Any]:
    """Runs the configured live provider for one surface/query (spec: `ci
    observe organic/aio/ai-mode/fanout QUERY`). Every provider (see
    observation/providers.py) always returns a status of
    available/unavailable/blocked/error -- this never raises on a blocked
    or unreachable network, and never fabricates a result. The default
    providers make no network call at all (this environment's own access
    to general external sites is a known, confirmed block -- see the
    observation package's docstring) and report `unavailable`."""
    if surface not in _OBSERVE_PROVIDERS:
        raise ValueError(f"unknown observation surface: {surface!r} (expected one of {sorted(_OBSERVE_PROVIDERS)})")
    provider = _OBSERVE_PROVIDERS[surface]
    result = provider.fetch(
        query, country or OBSERVATION_CONFIG.default_country, language or OBSERVATION_CONFIG.default_language,
        device or OBSERVATION_CONFIG.default_device,
    )
    return {
        "surface": surface, "query": query, "provider": result.provider, "status": result.status,
        "observed_at": result.observed_at, "error_message": result.error_message,
    }


# ---------------------------------------------------------------------------
# PHASE 14: Opportunity Score / Cross-Competitor Comparison
# ---------------------------------------------------------------------------

def compute_page_opportunity(config: AppConfig, page_id: str, competitor_page_ids: list[str] | None = None) -> dict[str, Any]:
    db = _db(config)
    return opportunity_pipeline.compute_page_opportunity(db, page_id, competitor_page_ids)


def compute_keyword_opportunity(
    config: AppConfig, keyword_id: str, our_page_id: str, competitor_page_ids: list[str] | None = None,
) -> dict[str, Any]:
    db = _db(config)
    return opportunity_pipeline.compute_keyword_opportunity(db, keyword_id, our_page_id, competitor_page_ids)


def get_opportunity(config: AppConfig, entity_type: str, entity_id: str, our_page_id: str | None = None) -> dict[str, Any] | None:
    db = _db(config)
    return opportunity_pipeline.get_opportunity(db, entity_type, entity_id, our_page_id)


def get_opportunity_detail(config: AppConfig, opportunity_id: str) -> dict[str, Any] | None:
    db = _db(config)
    return opportunity_pipeline.get_opportunity_detail(db, opportunity_id)


def list_opportunities(
    config: AppConfig, entity_type: str | None = None, limit: int = 200, offset: int = 0,
    min_commercial: float | None = None, min_ai_gap: float | None = None, min_content_gap: float | None = None,
    min_confidence: float | None = None,
) -> list[dict[str, Any]]:
    db = _db(config)
    return OpportunityRepository(db).list_analyses(
        entity_type=entity_type, limit=limit, offset=offset, min_commercial=min_commercial,
        min_ai_gap=min_ai_gap, min_content_gap=min_content_gap, min_confidence=min_confidence,
    )


def compare_pages(config: AppConfig, page_id_a: str, page_id_b: str) -> list[dict[str, Any]]:
    db = _db(config)
    return opportunity_pipeline.compare_pages(db, page_id_a, page_id_b)


def compare_domains(config: AppConfig, domain_id_a: str, domain_id_b: str) -> list[dict[str, Any]]:
    db = _db(config)
    return opportunity_pipeline.compare_domains(db, domain_id_a, domain_id_b)


def compare_keywords(config: AppConfig, keyword_id_a: str, keyword_id_b: str) -> list[dict[str, Any]]:
    db = _db(config)
    return opportunity_pipeline.compare_keywords(db, keyword_id_a, keyword_id_b)


def list_content_gaps_for_page(config: AppConfig, our_page_id: str) -> list[dict[str, Any]]:
    db = _db(config)
    return ContentGapRepository(db).list_for_our_page(our_page_id)


def recompute_all_opportunities(config: AppConfig, crawl_run_id: str | None = None) -> dict[str, int]:
    db = _db(config)
    return opportunity_pipeline.recompute_all(db, crawl_run_id)


def import_keyword_metrics(config: AppConfig, file_path: str) -> dict[str, Any]:
    db = _db(config)
    return import_keyword_metrics_file(db, file_path)


def export_opportunity_csv(config: AppConfig, out_dir: str) -> list[str]:
    from .opportunity.exporter import export_all as export_opportunity_all

    db = _db(config)
    return export_opportunity_all(db, out_dir)
