"""Persistence for PHASE 14 opportunity tables (migration 0006)."""

from __future__ import annotations

import json
from typing import Any

from ...database import Database, new_id


class KeywordMetricsRepository:
    def __init__(self, db: Database):
        self.db = db

    def record(
        self, query: str, source: str, observed_at: str, search_volume: int | None = None,
        impressions: int | None = None, clicks: int | None = None, ctr: float | None = None,
        trend: str | None = None, seasonality: str | None = None, related_query_count: int | None = None,
        cpc: float | None = None, competition: float | None = None,
    ) -> str | None:
        """Idempotent on (source, query, observed_at) -- spec section 16."""
        from ...job_registry import now_iso

        existing = self.db.query_one(
            "SELECT keyword_metric_id FROM ci_keyword_metrics WHERE source=? AND query=? AND observed_at=?",
            (source, query, observed_at),
        )
        if existing:
            return None
        metric_id = new_id("kwmetric_")
        self.db.execute(
            "INSERT INTO ci_keyword_metrics "
            "(keyword_metric_id, query, search_volume, impressions, clicks, ctr, trend, seasonality, "
            " related_query_count, cpc, competition, source, observed_at, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (metric_id, query, search_volume, impressions, clicks, ctr, trend, seasonality,
             related_query_count, cpc, competition, source, observed_at, now_iso()),
        )
        return metric_id

    def latest_for_query(self, query: str) -> dict[str, Any] | None:
        rows = self.db.query(
            "SELECT * FROM ci_keyword_metrics WHERE query=? ORDER BY observed_at DESC LIMIT 1", (query,)
        )
        return rows[0] if rows else None

    def list_for_query(self, query: str) -> list[dict[str, Any]]:
        return self.db.query("SELECT * FROM ci_keyword_metrics WHERE query=? ORDER BY observed_at", (query,))


class OpportunityRepository:
    """Manages ci_opportunity_analyses + its child tables (components,
    reasons, actions) as one unit -- recompute always replaces a prior
    opportunity's children rather than accumulating duplicates."""

    def __init__(self, db: Database):
        self.db = db

    def upsert_analysis(self, entity_type: str, entity_id: str, our_page_id: str | None, **fields: Any) -> str:
        from ...job_registry import now_iso

        existing = self.db.query_one(
            "SELECT opportunity_id FROM ci_opportunity_analyses WHERE entity_type=? AND entity_id=? AND our_page_id IS ?",
            (entity_type, entity_id, our_page_id),
        )
        now = now_iso()
        if existing:
            opportunity_id = existing["opportunity_id"]
            set_clause = ", ".join(f"{k}=?" for k in fields)
            self.db.execute(
                f"UPDATE ci_opportunity_analyses SET {set_clause}, computed_at=? WHERE opportunity_id=?",
                (*fields.values(), now, opportunity_id),
            )
        else:
            opportunity_id = new_id("opp_")
            columns = ["opportunity_id", "entity_type", "entity_id", "our_page_id", "computed_at", *fields.keys()]
            values = [opportunity_id, entity_type, entity_id, our_page_id, now, *fields.values()]
            self.db.execute(
                f"INSERT INTO ci_opportunity_analyses ({','.join(columns)}) VALUES ({','.join('?' for _ in values)})",
                values,
            )
        return opportunity_id

    def get_analysis(self, entity_type: str, entity_id: str, our_page_id: str | None = None) -> dict[str, Any] | None:
        return self.db.query_one(
            "SELECT * FROM ci_opportunity_analyses WHERE entity_type=? AND entity_id=? AND our_page_id IS ?",
            (entity_type, entity_id, our_page_id),
        )

    def get_by_id(self, opportunity_id: str) -> dict[str, Any] | None:
        return self.db.query_one("SELECT * FROM ci_opportunity_analyses WHERE opportunity_id=?", (opportunity_id,))

    def list_analyses(
        self, entity_type: str | None = None, limit: int = 200, offset: int = 0,
        min_commercial: float | None = None, min_ai_gap: float | None = None,
        min_content_gap: float | None = None, min_confidence: float | None = None,
    ) -> list[dict[str, Any]]:
        clauses, params = [], []
        if entity_type:
            clauses.append("entity_type=?")
            params.append(entity_type)
        if min_commercial is not None:
            clauses.append("commercial_opportunity_score >= ?")
            params.append(min_commercial)
        if min_ai_gap is not None:
            clauses.append("ai_opportunity_score >= ?")
            params.append(min_ai_gap)
        if min_content_gap is not None:
            clauses.append("content_gap_score >= ?")
            params.append(min_content_gap)
        if min_confidence is not None:
            clauses.append("confidence_value >= ?")
            params.append(min_confidence)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend([limit, offset])
        return self.db.query(
            f"SELECT * FROM ci_opportunity_analyses {where} "
            f"ORDER BY overall_opportunity_score IS NULL, overall_opportunity_score DESC LIMIT ? OFFSET ?",
            params,
        )

    def replace_components(self, opportunity_id: str, components: list[dict[str, Any]]) -> None:
        from ...job_registry import now_iso

        self.db.execute("DELETE FROM ci_opportunity_components WHERE opportunity_id=?", (opportunity_id,))
        now = now_iso()
        for c in components:
            self.db.execute(
                "INSERT INTO ci_opportunity_components "
                "(component_id, opportunity_id, component_name, value, weight, availability, evidence, computed_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (new_id("oppcomp_"), opportunity_id, c["component_name"], c["value"], c["weight"],
                 c["availability"], c["evidence"], now),
            )

    def components_for(self, opportunity_id: str) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM ci_opportunity_components WHERE opportunity_id=? ORDER BY component_name",
            (opportunity_id,),
        )

    def replace_reasons(self, opportunity_id: str, reasons: list[dict[str, Any]]) -> None:
        from ...job_registry import now_iso

        self.db.execute("DELETE FROM ci_opportunity_reasons WHERE opportunity_id=?", (opportunity_id,))
        now = now_iso()
        for r in reasons:
            self.db.execute(
                "INSERT INTO ci_opportunity_reasons "
                "(reason_id, opportunity_id, reason_code, reason_text, impact_score, evidence_reference, computed_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (new_id("oppreason_"), opportunity_id, r["reason_code"], r["reason_text"], r["impact_score"],
                 r["evidence_reference"], now),
            )

    def reasons_for(self, opportunity_id: str) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM ci_opportunity_reasons WHERE opportunity_id=? ORDER BY impact_score DESC",
            (opportunity_id,),
        )

    def replace_actions(self, opportunity_id: str, actions: list[dict[str, Any]]) -> None:
        from ...job_registry import now_iso

        self.db.execute("DELETE FROM ci_opportunity_actions WHERE opportunity_id=?", (opportunity_id,))
        now = now_iso()
        for a in actions:
            self.db.execute(
                "INSERT INTO ci_opportunity_actions "
                "(action_id, opportunity_id, action_code, priority, reason_code, target_page, target_keyword, computed_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (new_id("oppaction_"), opportunity_id, a["action_code"], a["priority"], a.get("reason_code"),
                 a.get("target_page"), a.get("target_keyword"), now),
            )

    def actions_for(self, opportunity_id: str) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM ci_opportunity_actions WHERE opportunity_id=? ORDER BY priority", (opportunity_id,)
        )


class ComparisonRepository:
    def __init__(self, db: Database):
        self.db = db

    def upsert(
        self, left_entity_type: str, left_entity_id: str, right_entity_type: str, right_entity_id: str,
        comparison_dimension: str, left_value: float | None, right_value: float | None, gap_value: float | None,
        winner: str, confidence: str, evidence: str | None,
    ) -> str:
        from ...job_registry import now_iso

        existing = self.db.query_one(
            "SELECT comparison_id FROM ci_competitor_comparisons WHERE left_entity_type=? AND left_entity_id=? "
            "AND right_entity_type=? AND right_entity_id=? AND comparison_dimension=?",
            (left_entity_type, left_entity_id, right_entity_type, right_entity_id, comparison_dimension),
        )
        now = now_iso()
        if existing:
            comparison_id = existing["comparison_id"]
            self.db.execute(
                "UPDATE ci_competitor_comparisons SET left_value=?, right_value=?, gap_value=?, winner=?, "
                "confidence=?, evidence=?, computed_at=? WHERE comparison_id=?",
                (left_value, right_value, gap_value, winner, confidence, evidence, now, comparison_id),
            )
        else:
            comparison_id = new_id("cmp_")
            self.db.execute(
                "INSERT INTO ci_competitor_comparisons "
                "(comparison_id, left_entity_type, left_entity_id, right_entity_type, right_entity_id, "
                " comparison_dimension, left_value, right_value, gap_value, winner, confidence, evidence, computed_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (comparison_id, left_entity_type, left_entity_id, right_entity_type, right_entity_id,
                 comparison_dimension, left_value, right_value, gap_value, winner, confidence, evidence, now),
            )
        return comparison_id

    def list_for_pair(self, left_entity_type: str, left_entity_id: str, right_entity_type: str,
                       right_entity_id: str) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM ci_competitor_comparisons WHERE left_entity_type=? AND left_entity_id=? "
            "AND right_entity_type=? AND right_entity_id=? ORDER BY comparison_dimension",
            (left_entity_type, left_entity_id, right_entity_type, right_entity_id),
        )

    def list_for_entity(self, entity_type: str, entity_id: str) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM ci_competitor_comparisons WHERE (left_entity_type=? AND left_entity_id=?) "
            "OR (right_entity_type=? AND right_entity_id=?) ORDER BY computed_at DESC",
            (entity_type, entity_id, entity_type, entity_id),
        )


class ContentGapRepository:
    def __init__(self, db: Database):
        self.db = db

    def upsert(self, our_page_id: str, competitor_page_id: str, result: Any) -> str:
        from ...job_registry import now_iso

        existing = self.db.query_one(
            "SELECT content_gap_id FROM ci_content_gaps WHERE our_page_id=? AND competitor_page_id=?",
            (our_page_id, competitor_page_id),
        )
        now = now_iso()
        payload = (
            json.dumps(result.missing_keywords, ensure_ascii=False),
            json.dumps(result.missing_subtopics, ensure_ascii=False),
            json.dumps(result.missing_entities, ensure_ascii=False),
            json.dumps(result.missing_questions, ensure_ascii=False),
            json.dumps(result.missing_numeric_facts, ensure_ascii=False),
            json.dumps(result.missing_comparison_dimensions, ensure_ascii=False),
            json.dumps(result.missing_primary_information, ensure_ascii=False),
            json.dumps(result.missing_freshness_evidence, ensure_ascii=False),
            json.dumps(result.missing_internal_link_topics, ensure_ascii=False),
            result.content_gap_score,
        )
        if existing:
            content_gap_id = existing["content_gap_id"]
            self.db.execute(
                "UPDATE ci_content_gaps SET missing_keywords_json=?, missing_subtopics_json=?, "
                "missing_entities_json=?, missing_questions_json=?, missing_numeric_facts_json=?, "
                "missing_comparison_dimensions_json=?, missing_primary_information_json=?, "
                "missing_freshness_evidence_json=?, missing_internal_link_topics_json=?, content_gap_score=?, "
                "computed_at=? WHERE content_gap_id=?",
                (*payload, now, content_gap_id),
            )
        else:
            content_gap_id = new_id("gap_")
            self.db.execute(
                "INSERT INTO ci_content_gaps "
                "(content_gap_id, our_page_id, competitor_page_id, missing_keywords_json, missing_subtopics_json, "
                " missing_entities_json, missing_questions_json, missing_numeric_facts_json, "
                " missing_comparison_dimensions_json, missing_primary_information_json, "
                " missing_freshness_evidence_json, missing_internal_link_topics_json, content_gap_score, computed_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (content_gap_id, our_page_id, competitor_page_id, *payload, now),
            )
        return content_gap_id

    def list_for_our_page(self, our_page_id: str) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM ci_content_gaps WHERE our_page_id=? ORDER BY content_gap_score DESC", (our_page_id,)
        )

    def get(self, our_page_id: str, competitor_page_id: str) -> dict[str, Any] | None:
        return self.db.query_one(
            "SELECT * FROM ci_content_gaps WHERE our_page_id=? AND competitor_page_id=?",
            (our_page_id, competitor_page_id),
        )
