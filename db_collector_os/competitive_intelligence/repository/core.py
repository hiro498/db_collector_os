"""Domain / crawl-run / crawl-url persistence.

Follows the same shape as db_collector_os.candidates.CandidateStore /
db_collector_os.fetching.queue.FetchQueue: plain classes wrapping a shared
``Database``, idempotent inserts keyed by the tables' UNIQUE constraints.
"""

from __future__ import annotations

from typing import Any

from ...database import Database, new_id
from ...job_registry import now_iso
from ..enums import CrawlRunStatus, CrawlUrlStatus

# Columns CrawlRunRepository.update_audit()/increment() may write. A fixed
# allow-list keeps the generic "build an UPDATE from kwargs" helper safe
# against SQL injection via column names.
_AUDIT_COLUMNS = {
    "discovered_total", "sitemap_discovered", "internal_discovered", "attempted_total",
    "fetched_success", "js_fallback_success", "canonical_duplicate", "noindex_count",
    "robots_blocked", "count_404", "count_other_4xx", "count_5xx", "count_timeout",
    "count_retry_failed", "excluded_count", "analyzed_pages", "unresolved_count",
    "converged", "completion_rate", "sitemap_phase_done", "sitemap_index_phase_done",
    "internal_link_phase_done", "pagination_phase_done", "site_aggregation_done",
}


class DomainRepository:
    def __init__(self, db: Database):
        self.db = db

    def get_or_create(self, domain: str, target_type: str, vertical: str = "general") -> dict[str, Any]:
        existing = self.db.query_one("SELECT * FROM ci_domains WHERE domain=?", (domain,))
        if existing:
            return existing
        domain_id = new_id("cidom_")
        now = now_iso()
        self.db.execute(
            "INSERT INTO ci_domains (domain_id, domain, vertical, target_type, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?)",
            (domain_id, domain, vertical, target_type, now, now),
        )
        return self.db.query_one("SELECT * FROM ci_domains WHERE domain_id=?", (domain_id,))

    def get(self, domain_id: str) -> dict[str, Any] | None:
        return self.db.query_one("SELECT * FROM ci_domains WHERE domain_id=?", (domain_id,))

    def list(self, limit: int = 200) -> list[dict[str, Any]]:
        return self.db.query("SELECT * FROM ci_domains ORDER BY updated_at DESC LIMIT ?", (limit,))


class CrawlRunRepository:
    def __init__(self, db: Database):
        self.db = db

    def create(self, domain_id: str, input_url: str, requested_mode: str, input_mode: str, vertical: str) -> str:
        crawl_run_id = new_id("cirun_")
        now = now_iso()
        self.db.execute(
            """INSERT INTO ci_crawl_runs
               (crawl_run_id, domain_id, input_url, requested_mode, input_mode, vertical,
                status, stop_requested, started_at)
               VALUES (?,?,?,?,?,?,?,0,?)""",
            (crawl_run_id, domain_id, input_url, requested_mode, input_mode, vertical,
             CrawlRunStatus.RUNNING, now),
        )
        return crawl_run_id

    def get(self, crawl_run_id: str) -> dict[str, Any] | None:
        return self.db.query_one("SELECT * FROM ci_crawl_runs WHERE crawl_run_id=?", (crawl_run_id,))

    def list_for_domain(self, domain_id: str, limit: int = 50) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM ci_crawl_runs WHERE domain_id=? ORDER BY started_at DESC LIMIT ?",
            (domain_id, limit),
        )

    def list_recent(self, limit: int = 100) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT r.*, d.domain AS domain FROM ci_crawl_runs r "
            "JOIN ci_domains d ON d.domain_id = r.domain_id "
            "ORDER BY r.started_at DESC LIMIT ?",
            (limit,),
        )

    def set_status(self, crawl_run_id: str, status: str, error_message: str | None = None) -> None:
        finished_at = now_iso() if status in (CrawlRunStatus.COMPLETED, CrawlRunStatus.FAILED) else None
        self.db.execute(
            "UPDATE ci_crawl_runs SET status=?, error_message=COALESCE(?, error_message), "
            "finished_at=COALESCE(?, finished_at) WHERE crawl_run_id=?",
            (status, error_message, finished_at, crawl_run_id),
        )

    def request_stop(self, crawl_run_id: str) -> None:
        self.db.execute("UPDATE ci_crawl_runs SET stop_requested=1 WHERE crawl_run_id=?", (crawl_run_id,))

    def is_stop_requested(self, crawl_run_id: str) -> bool:
        row = self.db.query_one("SELECT stop_requested FROM ci_crawl_runs WHERE crawl_run_id=?", (crawl_run_id,))
        return bool(row and row["stop_requested"])

    def clear_stop(self, crawl_run_id: str) -> None:
        """Called by resume() so a previously-stopped run can proceed again."""
        self.db.execute("UPDATE ci_crawl_runs SET stop_requested=0 WHERE crawl_run_id=?", (crawl_run_id,))

    def update_audit(self, crawl_run_id: str, **fields: Any) -> None:
        unknown = set(fields) - _AUDIT_COLUMNS
        if unknown:
            raise ValueError(f"not an audit column: {sorted(unknown)}")
        if not fields:
            return
        set_clause = ", ".join(f"{col}=?" for col in fields)
        self.db.execute(
            f"UPDATE ci_crawl_runs SET {set_clause} WHERE crawl_run_id=?",
            (*fields.values(), crawl_run_id),
        )


class CrawlUrlRepository:
    def __init__(self, db: Database):
        self.db = db

    def add(
        self,
        crawl_run_id: str,
        domain_id: str,
        url: str,
        normalized_url: str,
        discovered_by: str,
        source_url: str | None = None,
        crawl_depth: int = 0,
    ) -> tuple[str, bool]:
        """Idempotent per (crawl_run_id, normalized_url). Returns (crawl_url_id, created)."""
        existing = self.get_by_normalized(crawl_run_id, normalized_url)
        if existing:
            return existing["crawl_url_id"], False
        crawl_url_id = new_id("ciurl_")
        now = now_iso()
        self.db.execute(
            """INSERT INTO ci_crawl_urls
               (crawl_url_id, crawl_run_id, domain_id, url, normalized_url, discovered_by,
                source_url, crawl_depth, status, discovered_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (crawl_url_id, crawl_run_id, domain_id, url, normalized_url, discovered_by,
             source_url, crawl_depth, CrawlUrlStatus.DISCOVERED, now, now),
        )
        return crawl_url_id, True

    def get(self, crawl_url_id: str) -> dict[str, Any] | None:
        return self.db.query_one("SELECT * FROM ci_crawl_urls WHERE crawl_url_id=?", (crawl_url_id,))

    def get_by_normalized(self, crawl_run_id: str, normalized_url: str) -> dict[str, Any] | None:
        return self.db.query_one(
            "SELECT * FROM ci_crawl_urls WHERE crawl_run_id=? AND normalized_url=?",
            (crawl_run_id, normalized_url),
        )

    def list_by_status(self, crawl_run_id: str, statuses: tuple[str, ...], limit: int = 5000) -> list[dict[str, Any]]:
        placeholders = ",".join("?" for _ in statuses)
        return self.db.query(
            f"SELECT * FROM ci_crawl_urls WHERE crawl_run_id=? AND status IN ({placeholders}) "
            "ORDER BY crawl_depth, discovered_at LIMIT ?",
            (crawl_run_id, *statuses, limit),
        )

    def count_by_status(self, crawl_run_id: str) -> dict[str, int]:
        rows = self.db.query(
            "SELECT status, COUNT(*) AS n FROM ci_crawl_urls WHERE crawl_run_id=? GROUP BY status",
            (crawl_run_id,),
        )
        return {r["status"]: r["n"] for r in rows}

    def total_count(self, crawl_run_id: str) -> int:
        row = self.db.query_one("SELECT COUNT(*) AS n FROM ci_crawl_urls WHERE crawl_run_id=?", (crawl_run_id,))
        return row["n"] if row else 0

    def set_status(self, crawl_url_id: str, status: str, error_message: str | None = None) -> None:
        self.db.execute(
            "UPDATE ci_crawl_urls SET status=?, error_message=COALESCE(?, error_message), updated_at=? "
            "WHERE crawl_url_id=?",
            (status, error_message, now_iso(), crawl_url_id),
        )

    def mark_excluded(self, crawl_url_id: str, reason: str) -> None:
        self.db.execute(
            "UPDATE ci_crawl_urls SET status=?, exclusion_reason=?, updated_at=? WHERE crawl_url_id=?",
            (CrawlUrlStatus.EXCLUDED, reason, now_iso(), crawl_url_id),
        )

    def record_fetch_attempt(
        self,
        crawl_url_id: str,
        status: str,
        http_status: int | None = None,
        redirect_to: str | None = None,
        canonical_url: str | None = None,
        error_message: str | None = None,
    ) -> None:
        self.db.execute(
            """UPDATE ci_crawl_urls
               SET status=?, http_status=COALESCE(?, http_status), redirect_to=COALESCE(?, redirect_to),
                   canonical_url=COALESCE(?, canonical_url), error_message=?, fetch_attempts=fetch_attempts+1,
                   updated_at=?
               WHERE crawl_url_id=?""",
            (status, http_status, redirect_to, canonical_url, error_message, now_iso(), crawl_url_id),
        )

    def set_canonical_duplicate(self, crawl_url_id: str) -> None:
        self.db.execute(
            "UPDATE ci_crawl_urls SET is_canonical_duplicate=1, analysis_target=0, "
            "exclusion_reason='canonical_duplicate', updated_at=? WHERE crawl_url_id=?",
            (now_iso(), crawl_url_id),
        )

    def set_indexable(self, crawl_url_id: str, indexable: bool) -> None:
        self.db.execute(
            "UPDATE ci_crawl_urls SET indexable=?, updated_at=? WHERE crawl_url_id=?",
            (1 if indexable else 0, now_iso(), crawl_url_id),
        )

    def set_analysis_target(self, crawl_url_id: str, flag: bool) -> None:
        self.db.execute(
            "UPDATE ci_crawl_urls SET analysis_target=?, updated_at=? WHERE crawl_url_id=?",
            (1 if flag else 0, now_iso(), crawl_url_id),
        )

    def set_pagination(self, crawl_url_id: str, flag: bool) -> None:
        self.db.execute(
            "UPDATE ci_crawl_urls SET is_pagination=? WHERE crawl_url_id=?",
            (1 if flag else 0, crawl_url_id),
        )

    def list_all(
        self, crawl_run_id: str, limit: int = 200, offset: int = 0, status: str | None = None
    ) -> list[dict[str, Any]]:
        if status:
            return self.db.query(
                "SELECT * FROM ci_crawl_urls WHERE crawl_run_id=? AND status=? "
                "ORDER BY discovered_at LIMIT ? OFFSET ?",
                (crawl_run_id, status, limit, offset),
            )
        return self.db.query(
            "SELECT * FROM ci_crawl_urls WHERE crawl_run_id=? ORDER BY discovered_at LIMIT ? OFFSET ?",
            (crawl_run_id, limit, offset),
        )
