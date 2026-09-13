"""Crawl-run audit aggregation (spec section 11). Recomputes every counter
directly from `ci_crawl_urls`/`ci_pages` so it's always consistent with
their actual rows -- CrawlEngine calls this after each processing batch
rather than incrementing counters ad hoc while iterating.
"""

from __future__ import annotations

from typing import Any

from ...database import Database
from ..enums import CrawlUrlStatus
from ..repository.core import CrawlRunRepository

_TERMINAL_FOR_CONVERGENCE = (CrawlUrlStatus.COMPLETED, CrawlUrlStatus.EXCLUDED, CrawlUrlStatus.FAILED)


def recompute_audit(db: Database, crawl_run_id: str) -> dict[str, Any]:
    def count(sql: str, *params: Any) -> int:
        row = db.query_one(f"SELECT COUNT(*) AS n FROM {sql}", params)
        return row["n"] if row else 0

    discovered_total = count("ci_crawl_urls WHERE crawl_run_id=?", crawl_run_id)
    sitemap_discovered = count("ci_crawl_urls WHERE crawl_run_id=? AND discovered_by='sitemap'", crawl_run_id)
    internal_discovered = count(
        "ci_crawl_urls WHERE crawl_run_id=? AND discovered_by IN ('internal_link','pagination')", crawl_run_id
    )
    attempted_total = count("ci_crawl_urls WHERE crawl_run_id=? AND fetch_attempts > 0", crawl_run_id)
    fetched_success = count("ci_pages WHERE crawl_run_id=?", crawl_run_id)
    canonical_duplicate = count("ci_crawl_urls WHERE crawl_run_id=? AND is_canonical_duplicate=1", crawl_run_id)
    noindex_count = count("ci_pages WHERE crawl_run_id=? AND robots_meta LIKE '%noindex%'", crawl_run_id)
    robots_blocked = count("ci_crawl_urls WHERE crawl_run_id=? AND exclusion_reason='robots_blocked'", crawl_run_id)
    count_404 = count("ci_crawl_urls WHERE crawl_run_id=? AND http_status=404", crawl_run_id)
    count_other_4xx = count(
        "ci_crawl_urls WHERE crawl_run_id=? AND http_status BETWEEN 400 AND 499 AND http_status != 404",
        crawl_run_id,
    )
    count_5xx = count("ci_crawl_urls WHERE crawl_run_id=? AND http_status >= 500", crawl_run_id)
    count_timeout = count("ci_crawl_urls WHERE crawl_run_id=? AND error_message='timeout'", crawl_run_id)
    count_retry_failed = count("ci_crawl_urls WHERE crawl_run_id=? AND status='failed'", crawl_run_id)
    excluded_count = count("ci_crawl_urls WHERE crawl_run_id=? AND status='excluded'", crawl_run_id)
    analyzed_pages = count("ci_pages WHERE crawl_run_id=? AND analysis_target=1", crawl_run_id)
    unresolved_count = discovered_total - count(
        "ci_crawl_urls WHERE crawl_run_id=? AND status IN ('completed','excluded','failed')", crawl_run_id
    )
    completion_rate = (discovered_total - unresolved_count) / discovered_total if discovered_total else 1.0

    audit = {
        "discovered_total": discovered_total,
        "sitemap_discovered": sitemap_discovered,
        "internal_discovered": internal_discovered,
        "attempted_total": attempted_total,
        "fetched_success": fetched_success,
        # No real JS renderer is wired up in this P0 (see fetcher.py) --
        # reporting a fabricated non-zero count here would misrepresent
        # capability that doesn't exist (spec section 46).
        "js_fallback_success": 0,
        "canonical_duplicate": canonical_duplicate,
        "noindex_count": noindex_count,
        "robots_blocked": robots_blocked,
        "count_404": count_404,
        "count_other_4xx": count_other_4xx,
        "count_5xx": count_5xx,
        "count_timeout": count_timeout,
        "count_retry_failed": count_retry_failed,
        "excluded_count": excluded_count,
        "analyzed_pages": analyzed_pages,
        "unresolved_count": unresolved_count,
        "completion_rate": round(completion_rate, 4),
    }
    CrawlRunRepository(db).update_audit(crawl_run_id, **audit)
    return audit
