"""Persistence for PHASE 15 production-validation tables (migration 0007)."""

from __future__ import annotations

import json
from typing import Any

from ...database import Database, new_id
from ...job_registry import now_iso


class ValidationRunRepository:
    def __init__(self, db: Database):
        self.db = db

    def create(
        self, target_url: str, max_pages: int | None, rate_limit_delay_seconds: float | None,
        output_dir: str | None, our_domain_run_id: str | None = None,
    ) -> str:
        run_id = new_id("valrun_")
        self.db.execute(
            "INSERT INTO ci_validation_runs "
            "(validation_run_id, target_url, our_domain_run_id, max_pages, rate_limit_delay_seconds, "
            " output_dir, status, started_at) VALUES (?,?,?,?,?,?,?,?)",
            (run_id, target_url, our_domain_run_id, max_pages, rate_limit_delay_seconds, output_dir,
             "RUNNING", now_iso()),
        )
        return run_id

    def set_crawl_run(self, validation_run_id: str, crawl_run_id: str, domain_id: str) -> None:
        self.db.execute(
            "UPDATE ci_validation_runs SET crawl_run_id=?, domain_id=? WHERE validation_run_id=?",
            (crawl_run_id, domain_id, validation_run_id),
        )

    def complete(
        self, validation_run_id: str, status: str, production_validation_status: str | None,
        top50_ab_rate: float | None, top50_ab_rate_is_human_audited: bool, summary: dict[str, Any],
        error_message: str | None = None,
    ) -> None:
        self.db.execute(
            "UPDATE ci_validation_runs SET status=?, production_validation_status=?, top50_ab_rate=?, "
            "top50_ab_rate_is_human_audited=?, summary_json=?, completed_at=?, error_message=? "
            "WHERE validation_run_id=?",
            (status, production_validation_status, top50_ab_rate, int(top50_ab_rate_is_human_audited),
             json.dumps(summary, ensure_ascii=False, default=str), now_iso(), error_message, validation_run_id),
        )

    def get(self, validation_run_id: str) -> dict[str, Any] | None:
        return self.db.query_one("SELECT * FROM ci_validation_runs WHERE validation_run_id=?", (validation_run_id,))

    def list_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.db.query("SELECT * FROM ci_validation_runs ORDER BY started_at DESC LIMIT ?", (limit,))


class DomainKeywordSummaryRepository:
    def __init__(self, db: Database):
        self.db = db

    def replace_all(self, validation_run_id: str, rows: list[dict[str, Any]]) -> None:
        self.db.execute(
            "DELETE FROM ci_domain_keyword_summary WHERE validation_run_id=?", (validation_run_id,)
        )
        now = now_iso()
        for r in rows:
            self.db.execute(
                "INSERT INTO ci_domain_keyword_summary "
                "(summary_id, validation_run_id, keyword, normalized_keyword, keyword_id, pages_count, "
                " page_types_json, best_keyword_score, avg_keyword_score, total_occurrences, title_occurrences, "
                " h1_occurrences, heading_occurrences, body_occurrences, anchor_occurrences, "
                " site_structure_score, cross_page_score, cluster_id, cluster_is_representative, "
                " primary_intent, secondary_intents_json, intent_confidence, commercial_score, "
                " transactional_signal, comparison_signal, review_signal, ranking_signal, price_signal, "
                " affiliate_relevance, monetization_score, money_keyword_class, is_noise, noise_reason, "
                " audit_class_auto, audit_class, audit_note, computed_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    new_id("dks_"), validation_run_id, r["keyword"], r["normalized_keyword"], r.get("keyword_id"),
                    r["pages_count"], json.dumps(r["page_types"], ensure_ascii=False), r["best_keyword_score"],
                    r["avg_keyword_score"], r["total_occurrences"], r["title_occurrences"], r["h1_occurrences"],
                    r["heading_occurrences"], r["body_occurrences"], r["anchor_occurrences"],
                    r["site_structure_score"], r["cross_page_score"], r.get("cluster_id"),
                    int(r.get("cluster_is_representative", True)), r.get("primary_intent"),
                    json.dumps(r.get("secondary_intents", []), ensure_ascii=False), r.get("intent_confidence"),
                    r.get("commercial_score"), int(r.get("transactional_signal", False)),
                    int(r.get("comparison_signal", False)), int(r.get("review_signal", False)),
                    int(r.get("ranking_signal", False)), int(r.get("price_signal", False)),
                    r.get("affiliate_relevance"), r.get("monetization_score"), r.get("money_keyword_class"),
                    int(r.get("is_noise", False)), r.get("noise_reason"), r.get("audit_class_auto"),
                    r.get("audit_class"), r.get("audit_note"), now,
                ),
            )

    def list_for_run(self, validation_run_id: str, limit: int = 100_000, offset: int = 0) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM ci_domain_keyword_summary WHERE validation_run_id=? "
            "ORDER BY best_keyword_score DESC LIMIT ? OFFSET ?",
            (validation_run_id, limit, offset),
        )

    def get(self, validation_run_id: str, normalized_keyword: str) -> dict[str, Any] | None:
        return self.db.query_one(
            "SELECT * FROM ci_domain_keyword_summary WHERE validation_run_id=? AND normalized_keyword=?",
            (validation_run_id, normalized_keyword),
        )

    def set_human_audit(
        self, validation_run_id: str, normalized_keyword: str, audit_class: str | None, audit_note: str | None,
    ) -> bool:
        cursor = self.db.execute(
            "UPDATE ci_domain_keyword_summary SET audit_class=?, audit_note=? "
            "WHERE validation_run_id=? AND normalized_keyword=?",
            (audit_class, audit_note, validation_run_id, normalized_keyword),
        )
        return cursor.rowcount > 0


class TargetKeywordPriorityRepository:
    def __init__(self, db: Database):
        self.db = db

    def replace_all(self, validation_run_id: str, rows: list[dict[str, Any]]) -> None:
        self.db.execute(
            "DELETE FROM ci_target_keyword_priorities WHERE validation_run_id=?", (validation_run_id,)
        )
        now = now_iso()
        for r in rows:
            self.db.execute(
                "INSERT INTO ci_target_keyword_priorities "
                "(priority_id, validation_run_id, priority_rank, keyword, normalized_keyword, keyword_id, "
                " intent, commercial_score, money_keyword_class, competitor_usage_strength, "
                " competitor_page_count, best_competitor_page_id, best_competitor_page_url, "
                " best_competitor_score, ai_readiness, organic_rank, aio_cited, ai_mode_cited, "
                " citation_frequency, fanout_visibility, content_gap_score, opportunity_score, score_status, "
                " confidence_label, confidence_value, top_reason_code, top_reason_text, recommended_action, "
                " demand_status, search_volume, trend, cpc, competition, blue_ocean_candidate, "
                " blue_ocean_candidate_status, computed_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    new_id("tkp_"), validation_run_id, r["priority_rank"], r["keyword"], r["normalized_keyword"],
                    r.get("keyword_id"), r.get("intent"), r.get("commercial_score"), r.get("money_keyword_class"),
                    r.get("competitor_usage_strength"), r.get("competitor_page_count"),
                    r.get("best_competitor_page_id"), r.get("best_competitor_page_url"),
                    r.get("best_competitor_score"), r.get("ai_readiness"), r.get("organic_rank"),
                    r.get("aio_cited"), r.get("ai_mode_cited"), r.get("citation_frequency"),
                    r.get("fanout_visibility"), r.get("content_gap_score"), r.get("opportunity_score"),
                    r.get("score_status"), r.get("confidence_label"), r.get("confidence_value"),
                    r.get("top_reason_code"), r.get("top_reason_text"), r.get("recommended_action"),
                    r.get("demand_status"), r.get("search_volume"), r.get("trend"), r.get("cpc"),
                    r.get("competition"),
                    None if r.get("blue_ocean_candidate") is None else int(r["blue_ocean_candidate"]),
                    r.get("blue_ocean_candidate_status"), now,
                ),
            )

    def list_for_run(self, validation_run_id: str, limit: int = 100_000, offset: int = 0) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM ci_target_keyword_priorities WHERE validation_run_id=? "
            "ORDER BY priority_rank LIMIT ? OFFSET ?",
            (validation_run_id, limit, offset),
        )
