"""Persistence for PHASE 13 observation tables (migration 0005)."""

from __future__ import annotations

from typing import Any

from ....database import Database, new_id
from ....job_registry import now_iso

_VISIBILITY_COLUMNS = {
    "organic_rank", "organic_top3", "organic_top10", "organic_top20", "organic_top100", "organic_observed_at",
    "aio_cited", "aio_citation_position", "aio_first_seen", "aio_last_seen", "aio_observation_count",
    "aio_citation_count", "aio_citation_frequency", "aio_persistence_score",
    "ai_mode_cited", "ai_mode_citation_position", "ai_mode_first_seen", "ai_mode_last_seen",
    "ai_mode_observation_count", "ai_mode_citation_count", "ai_mode_citation_frequency",
    "ai_mode_persistence_score",
    "fanout_queries_total", "fanout_queries_observed", "fanout_top10_count", "fanout_top20_count",
    "fanout_citation_count", "fanout_visibility_rate",
    "readiness_vs_reality_class", "organic_aio_cross_class",
    "signal_high_readiness_not_cited", "signal_low_rank_but_cited", "signal_high_rank_not_cited",
    "signal_fanout_visible_not_root_visible", "signal_aio_only", "signal_ai_mode_only",
    "signal_aio_and_ai_mode", "signal_organic_only",
}


class SerpObservationRepository:
    def __init__(self, db: Database):
        self.db = db

    def record(
        self, query: str, country: str, language: str, device: str, observed_at: str, provider: str,
        status: str, keyword_id: str | None = None, response_hash: str | None = None,
        raw_reference: str | None = None, results: list[dict[str, Any]] | None = None,
    ) -> str | None:
        """Idempotent on (query, country, language, device, observed_at,
        provider) -- a duplicate call is a no-op and returns None so
        callers (the importer) can count it as skipped rather than
        silently re-inserting results."""
        existing = self.db.query_one(
            "SELECT serp_observation_id FROM ci_serp_observations "
            "WHERE query=? AND country=? AND language=? AND device=? AND observed_at=? AND provider=?",
            (query, country, language, device, observed_at, provider),
        )
        if existing:
            return None
        observation_id = new_id("serpobs_")
        self.db.execute(
            "INSERT INTO ci_serp_observations "
            "(serp_observation_id, query, keyword_id, country, language, device, observed_at, provider, "
            " status, response_hash, raw_reference, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (observation_id, query, keyword_id, country, language, device, observed_at, provider,
             status, response_hash, raw_reference, now_iso()),
        )
        for result in results or []:
            self.db.execute(
                "INSERT INTO ci_serp_observation_results "
                "(serp_result_id, serp_observation_id, result_position, result_url, normalized_url, "
                " result_domain, title, snippet, result_type) VALUES (?,?,?,?,?,?,?,?,?)",
                (new_id("serpres_"), observation_id, result["result_position"], result["result_url"],
                 result["normalized_url"], result["result_domain"], result.get("title"), result.get("snippet"),
                 result.get("result_type", "organic")),
            )
        return observation_id

    def list_for_query(self, query: str, country: str, language: str, device: str) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM ci_serp_observations WHERE query=? AND country=? AND language=? AND device=? "
            "ORDER BY observed_at DESC",
            (query, country, language, device),
        )

    def latest_for_query(self, query: str, country: str, language: str, device: str) -> dict[str, Any] | None:
        rows = self.list_for_query(query, country, language, device)
        return rows[0] if rows else None

    def results_for_observation(self, observation_id: str) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM ci_serp_observation_results WHERE serp_observation_id=? ORDER BY result_position",
            (observation_id,),
        )

    def find_result_by_url(self, observation_id: str, normalized_url: str) -> dict[str, Any] | None:
        return self.db.query_one(
            "SELECT * FROM ci_serp_observation_results WHERE serp_observation_id=? AND normalized_url=?",
            (observation_id, normalized_url),
        )


class AioObservationRepository:
    def __init__(self, db: Database):
        self.db = db

    def record(
        self, query: str, country: str, language: str, device: str, observed_at: str, provider: str,
        status: str, keyword_id: str | None = None, aio_present: bool | None = None,
        aio_text_hash: str | None = None, response_hash: str | None = None, raw_reference: str | None = None,
        citations: list[dict[str, Any]] | None = None,
    ) -> str | None:
        existing = self.db.query_one(
            "SELECT aio_observation_id FROM ci_aio_observations "
            "WHERE query=? AND country=? AND language=? AND device=? AND observed_at=? AND provider=?",
            (query, country, language, device, observed_at, provider),
        )
        if existing:
            return None
        observation_id = new_id("aioobs_")
        citations = citations or []
        self.db.execute(
            "INSERT INTO ci_aio_observations "
            "(aio_observation_id, query, keyword_id, country, language, device, observed_at, provider, status, "
            " aio_present, aio_text_hash, citation_count, response_hash, raw_reference, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (observation_id, query, keyword_id, country, language, device, observed_at, provider, status,
             None if aio_present is None else int(aio_present), aio_text_hash, len(citations),
             response_hash, raw_reference, now_iso()),
        )
        for c in citations:
            self.db.execute(
                "INSERT INTO ci_aio_citations "
                "(aio_citation_id, aio_observation_id, citation_position, citation_url, normalized_url, "
                " citation_domain, citation_anchor_text, citation_context, citation_source_type) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (new_id("aiocit_"), observation_id, c.get("citation_position"), c["citation_url"],
                 c["normalized_url"], c["citation_domain"], c.get("citation_anchor_text"),
                 c.get("citation_context"), c.get("citation_source_type")),
            )
        return observation_id

    def list_for_query(self, query: str, country: str, language: str, device: str) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM ci_aio_observations WHERE query=? AND country=? AND language=? AND device=? "
            "ORDER BY observed_at",
            (query, country, language, device),
        )

    def citations_for_observation(self, observation_id: str) -> list[dict[str, Any]]:
        return self.db.query("SELECT * FROM ci_aio_citations WHERE aio_observation_id=?", (observation_id,))

    def citations_for_url(self, normalized_url: str) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT c.*, o.query, o.observed_at FROM ci_aio_citations c "
            "JOIN ci_aio_observations o ON o.aio_observation_id = c.aio_observation_id "
            "WHERE c.normalized_url=? ORDER BY o.observed_at",
            (normalized_url,),
        )


class AiModeObservationRepository:
    def __init__(self, db: Database):
        self.db = db

    def record(
        self, query: str, country: str, language: str, device: str, observed_at: str, provider: str,
        status: str, keyword_id: str | None = None, response_hash: str | None = None,
        raw_reference: str | None = None, citations: list[dict[str, Any]] | None = None,
    ) -> str | None:
        existing = self.db.query_one(
            "SELECT ai_mode_observation_id FROM ci_ai_mode_observations "
            "WHERE query=? AND country=? AND language=? AND device=? AND observed_at=? AND provider=?",
            (query, country, language, device, observed_at, provider),
        )
        if existing:
            return None
        observation_id = new_id("aimodeobs_")
        citations = citations or []
        self.db.execute(
            "INSERT INTO ci_ai_mode_observations "
            "(ai_mode_observation_id, query, keyword_id, country, language, device, observed_at, provider, "
            " status, response_hash, citation_count, raw_reference, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (observation_id, query, keyword_id, country, language, device, observed_at, provider, status,
             response_hash, len(citations), raw_reference, now_iso()),
        )
        for c in citations:
            self.db.execute(
                "INSERT INTO ci_ai_mode_citations "
                "(ai_mode_citation_id, ai_mode_observation_id, citation_position, citation_url, normalized_url, "
                " citation_domain, citation_anchor_text, citation_context) VALUES (?,?,?,?,?,?,?,?)",
                (new_id("aimodecit_"), observation_id, c.get("citation_position"), c["citation_url"],
                 c["normalized_url"], c["citation_domain"], c.get("citation_anchor_text"), c.get("citation_context")),
            )
        return observation_id

    def list_for_query(self, query: str, country: str, language: str, device: str) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM ci_ai_mode_observations WHERE query=? AND country=? AND language=? AND device=? "
            "ORDER BY observed_at",
            (query, country, language, device),
        )

    def citations_for_observation(self, observation_id: str) -> list[dict[str, Any]]:
        return self.db.query("SELECT * FROM ci_ai_mode_citations WHERE ai_mode_observation_id=?", (observation_id,))

    def citations_for_url(self, normalized_url: str) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT c.*, o.query, o.observed_at FROM ci_ai_mode_citations c "
            "JOIN ci_ai_mode_observations o ON o.ai_mode_observation_id = c.ai_mode_observation_id "
            "WHERE c.normalized_url=? ORDER BY o.observed_at",
            (normalized_url,),
        )


class FanoutObservationRepository:
    def __init__(self, db: Database):
        self.db = db

    def record(
        self, fanout_query_id: str, parent_query: str, fanout_query: str, fanout_intent: str,
        country: str, language: str, device: str, observed_at: str, provider: str, status: str,
        target_page_id: str | None = None, target_rank: int | None = None, target_cited: bool | None = None,
        result_urls: list[str] | None = None, response_hash: str | None = None, raw_reference: str | None = None,
    ) -> str:
        import json

        observation_id = new_id("fanoutobs_")
        self.db.execute(
            "INSERT INTO ci_fanout_observations "
            "(fanout_observation_id, fanout_query_id, parent_query, fanout_query, fanout_intent, country, "
            " language, device, observed_at, provider, status, target_page_id, target_rank, target_cited, "
            " result_urls_json, response_hash, raw_reference, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (observation_id, fanout_query_id, parent_query, fanout_query, fanout_intent, country, language,
             device, observed_at, provider, status, target_page_id, target_rank,
             None if target_cited is None else int(target_cited),
             json.dumps(result_urls or [], ensure_ascii=False), response_hash, raw_reference, now_iso()),
        )
        return observation_id

    def list_for_page(self, page_id: str) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM ci_fanout_observations WHERE target_page_id=? ORDER BY observed_at", (page_id,)
        )

    def list_for_fanout_query(self, fanout_query_id: str) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM ci_fanout_observations WHERE fanout_query_id=? ORDER BY observed_at",
            (fanout_query_id,),
        )


class PageVisibilityRepository:
    def __init__(self, db: Database):
        self.db = db

    def upsert(self, page_id: str, crawl_run_id: str, **fields: Any) -> None:
        unknown = set(fields) - _VISIBILITY_COLUMNS
        if unknown:
            raise ValueError(f"unknown page_visibility field(s): {sorted(unknown)}")
        now = now_iso()
        existing = self.db.query_one("SELECT page_id FROM ci_ai_page_visibility WHERE page_id=?", (page_id,))
        if existing:
            set_clause = ", ".join(f"{k}=?" for k in fields)
            self.db.execute(
                f"UPDATE ci_ai_page_visibility SET {set_clause}, computed_at=? WHERE page_id=?",
                (*fields.values(), now, page_id),
            )
            return
        columns = ["page_id", "crawl_run_id", "computed_at", *fields.keys()]
        values = [page_id, crawl_run_id, now, *fields.values()]
        self.db.execute(
            f"INSERT INTO ci_ai_page_visibility ({','.join(columns)}) VALUES ({','.join('?' for _ in values)})",
            values,
        )

    def get(self, page_id: str) -> dict[str, Any] | None:
        return self.db.query_one("SELECT * FROM ci_ai_page_visibility WHERE page_id=?", (page_id,))

    def list_for_run(self, crawl_run_id: str, limit: int = 200, offset: int = 0) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM ci_ai_page_visibility WHERE crawl_run_id=? ORDER BY page_id LIMIT ? OFFSET ?",
            (crawl_run_id, limit, offset),
        )


class ImportBatchRepository:
    def __init__(self, db: Database):
        self.db = db

    def record(
        self, file_path: str, file_hash: str, observation_type: str, provider: str | None,
        imported_count: int, skipped_duplicate_count: int, error_count: int,
    ) -> str | None:
        existing = self.db.query_one(
            "SELECT import_batch_id FROM ci_observation_import_batches WHERE file_hash=? AND observation_type=?",
            (file_hash, observation_type),
        )
        if existing:
            return None
        batch_id = new_id("import_")
        self.db.execute(
            "INSERT INTO ci_observation_import_batches "
            "(import_batch_id, file_path, file_hash, provider, observation_type, imported_count, "
            " skipped_duplicate_count, error_count, imported_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (batch_id, file_path, file_hash, provider, observation_type, imported_count,
             skipped_duplicate_count, error_count, now_iso()),
        )
        return batch_id

    def list_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM ci_observation_import_batches ORDER BY imported_at DESC LIMIT ?", (limit,)
        )

    def get(self, import_batch_id: str) -> dict[str, Any] | None:
        return self.db.query_one(
            "SELECT * FROM ci_observation_import_batches WHERE import_batch_id=?", (import_batch_id,)
        )


class GscObservationRepository:
    """Section 17: manually-imported GSC data only -- no OAuth/API call
    anywhere in this codebase."""

    def __init__(self, db: Database):
        self.db = db

    def record(
        self, gsc_query: str, gsc_page: str, normalized_page: str, observed_date: str,
        country: str | None = None, device: str | None = None, data_source_category: str = "search",
        impressions: int | None = None, clicks: int | None = None, ctr: float | None = None,
        position: float | None = None,
    ) -> str | None:
        existing = self.db.query_one(
            "SELECT gsc_observation_id FROM ci_gsc_observations WHERE gsc_query=? AND normalized_page=? "
            "AND country IS ? AND device IS ? AND observed_date=? AND data_source_category=?",
            (gsc_query, normalized_page, country, device, observed_date, data_source_category),
        )
        if existing:
            return None
        observation_id = new_id("gsc_")
        self.db.execute(
            "INSERT INTO ci_gsc_observations "
            "(gsc_observation_id, gsc_query, gsc_page, normalized_page, country, device, data_source_category, "
            " impressions, clicks, ctr, position, observed_date, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (observation_id, gsc_query, gsc_page, normalized_page, country, device, data_source_category,
             impressions, clicks, ctr, position, observed_date, now_iso()),
        )
        return observation_id

    def list_for_page(self, normalized_page: str) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM ci_gsc_observations WHERE normalized_page=? ORDER BY observed_date", (normalized_page,)
        )
