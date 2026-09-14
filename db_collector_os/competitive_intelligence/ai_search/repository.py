"""Persistence for PHASE 12 tables (migration 0004)."""

from __future__ import annotations

from typing import Any

from ...database import Database, new_id
from ...job_registry import now_iso

# Columns write_analysis() may set on ci_ai_page_analysis. A fixed
# allow-list keeps the generic "build an UPSERT from kwargs" helper safe
# against SQL injection via column names, matching the pattern used
# throughout competitive_intelligence/repository/*.py.
_ANALYSIS_COLUMNS = {
    "organic_visibility_score", "aio_citation_score", "ai_mode_citation_score", "fanout_coverage_score",
    "proprietary_information_score", "evidence_freshness_score", "source_affinity_score",
    "ai_search_total_score", "ai_citation_readiness_score",
    "primary_source_signal", "firsthand_signal", "proprietary_data_signal", "derived_metric_count",
    "unique_fact_count", "verifiable_fact_count", "sample_size_mentions", "methodology_signal",
    "source_traceability_score",
    "numeric_fact_count", "derived_numeric_fact_count", "comparison_numeric_fact_count",
    "ratio_percentage_count", "ranking_numeric_fact_count", "sample_size_count", "numeric_fact_quality_score",
    "comparison_entity_count", "comparison_dimension_count", "normalized_comparison_signal",
    "same_condition_comparison_signal", "derived_comparison_metric_count", "comparison_source_traceability",
    "comparison_information_score",
    "published_at", "modified_at", "data_updated_at", "freshness_timestamp_score",
    "evidence_change_score", "meaningful_update_signal",
    "answer_in_first_100_words", "key_fact_in_first_100_words", "comparison_result_near_top",
    "summary_near_top", "aio_extractability_score",
    "subtopic_count", "related_question_count", "entity_coverage_count", "evidence_block_count",
    "ai_mode_content_coverage_score",
    "fanout_content_coverage_score",
    "site_author_identity_signal", "editorial_policy_signal", "about_page_signal",
    "contact_transparency_signal", "source_citation_consistency", "repeat_entity_coverage",
    "topic_specialization_signal", "source_transparency_score", "external_source_preference_status",
    "organic_rank", "organic_top10", "organic_top20", "serp_observed_at",
    "aio_cited", "aio_citation_position", "aio_observed_at",
    "ai_mode_cited", "ai_mode_citation_position", "ai_mode_observed_at",
    "citation_first_seen", "citation_last_seen", "citation_observation_count", "citation_persistence_score",
    "extractor_version",
}


class AiPageAnalysisRepository:
    def __init__(self, db: Database):
        self.db = db

    def upsert(self, page_id: str, crawl_run_id: str, **fields: Any) -> None:
        unknown = set(fields) - _ANALYSIS_COLUMNS
        if unknown:
            raise ValueError(f"unknown ai_page_analysis field(s): {sorted(unknown)}")
        now = now_iso()
        existing = self.db.query_one("SELECT page_id FROM ci_ai_page_analysis WHERE page_id=?", (page_id,))
        if existing:
            set_clause = ", ".join(f"{k}=?" for k in fields)
            self.db.execute(
                f"UPDATE ci_ai_page_analysis SET {set_clause}, computed_at=? WHERE page_id=?",
                (*fields.values(), now, page_id),
            )
            return
        columns = ["page_id", "crawl_run_id", "computed_at", *fields.keys()]
        values = [page_id, crawl_run_id, now, *fields.values()]
        self.db.execute(
            f"INSERT INTO ci_ai_page_analysis ({','.join(columns)}) VALUES ({','.join('?' for _ in values)})",
            values,
        )

    def get(self, page_id: str) -> dict[str, Any] | None:
        return self.db.query_one("SELECT * FROM ci_ai_page_analysis WHERE page_id=?", (page_id,))

    def list_for_run(self, crawl_run_id: str, limit: int = 200, offset: int = 0) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM ci_ai_page_analysis WHERE crawl_run_id=? ORDER BY ai_citation_readiness_score DESC "
            "LIMIT ? OFFSET ?",
            (crawl_run_id, limit, offset),
        )


class AiNumericFactRepository:
    def __init__(self, db: Database):
        self.db = db

    def replace_for_page(self, page_id: str, facts: list[dict[str, Any]], extractor_version: str) -> None:
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM ci_ai_numeric_facts WHERE page_id=?", (page_id,))
            now = now_iso()
            for fact in facts:
                conn.execute(
                    "INSERT INTO ci_ai_numeric_facts "
                    "(fact_id, page_id, fact_type, signal_value, source_text, html_element, page_section, "
                    " confidence, extractor_version, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (new_id("aifact_"), page_id, fact["fact_type"], fact.get("signal_value"),
                     fact.get("source_text"), fact.get("html_element"), fact.get("page_section"),
                     fact.get("confidence", 0.5), extractor_version, now),
                )

    def list_for_page(self, page_id: str) -> list[dict[str, Any]]:
        return self.db.query("SELECT * FROM ci_ai_numeric_facts WHERE page_id=?", (page_id,))


class AiComparisonRepository:
    def __init__(self, db: Database):
        self.db = db

    def replace_for_page(self, page_id: str, comparisons: list[dict[str, Any]], extractor_version: str) -> None:
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM ci_ai_comparisons WHERE page_id=?", (page_id,))
            now = now_iso()
            for c in comparisons:
                conn.execute(
                    "INSERT INTO ci_ai_comparisons "
                    "(comparison_id, page_id, structure_type, entity_count, dimension_count, normalized, "
                    " same_condition, source_text, html_element, confidence, extractor_version, created_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (new_id("aicmp_"), page_id, c["structure_type"], c.get("entity_count", 0),
                     c.get("dimension_count", 0), int(c.get("normalized", False)),
                     int(c.get("same_condition", False)), c.get("source_text"), c.get("html_element"),
                     c.get("confidence", 0.5), extractor_version, now),
                )

    def list_for_page(self, page_id: str) -> list[dict[str, Any]]:
        return self.db.query("SELECT * FROM ci_ai_comparisons WHERE page_id=?", (page_id,))


class AiFanoutQueryRepository:
    def __init__(self, db: Database):
        self.db = db

    def replace_for_page(self, page_id: str, candidates: list[dict[str, Any]]) -> None:
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM ci_ai_fanout_queries WHERE page_id=?", (page_id,))
            now = now_iso()
            for c in candidates:
                conn.execute(
                    "INSERT INTO ci_ai_fanout_queries "
                    "(fanout_query_id, page_id, base_keyword, subquery_text, intent_class, covered_by_content, "
                    " serp_observed, created_at) VALUES (?,?,?,?,?,?,?,?)",
                    (new_id("aifq_"), page_id, c["base_keyword"], c["subquery_text"], c["intent_class"],
                     int(c.get("covered_by_content", False)), None, now),
                )

    def list_for_page(self, page_id: str) -> list[dict[str, Any]]:
        return self.db.query("SELECT * FROM ci_ai_fanout_queries WHERE page_id=?", (page_id,))


class AiFreshnessEventRepository:
    def __init__(self, db: Database):
        self.db = db

    def replace_for_page(self, page_id: str, events: list[dict[str, Any]], extractor_version: str) -> None:
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM ci_ai_freshness_events WHERE page_id=?", (page_id,))
            now = now_iso()
            for e in events:
                conn.execute(
                    "INSERT INTO ci_ai_freshness_events "
                    "(freshness_event_id, page_id, event_type, before_value, after_value, source_text, "
                    " html_element, confidence, extractor_version, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (new_id("aifresh_"), page_id, e["event_type"], e.get("before_value"), e.get("after_value"),
                     e.get("source_text"), e.get("html_element"), e.get("confidence", 0.5),
                     extractor_version, now),
                )

    def list_for_page(self, page_id: str) -> list[dict[str, Any]]:
        return self.db.query("SELECT * FROM ci_ai_freshness_events WHERE page_id=?", (page_id,))


class AiCitationObservationRepository:
    """Schema-only store for future/aio_observation.py and
    future/ai_mode_observation.py -- nothing in this phase writes here."""

    def __init__(self, db: Database):
        self.db = db

    def list_for_page(self, page_id: str, surface: str | None = None) -> list[dict[str, Any]]:
        if surface:
            return self.db.query(
                "SELECT * FROM ci_ai_citation_observations WHERE page_id=? AND surface=?", (page_id, surface)
            )
        return self.db.query("SELECT * FROM ci_ai_citation_observations WHERE page_id=?", (page_id,))
