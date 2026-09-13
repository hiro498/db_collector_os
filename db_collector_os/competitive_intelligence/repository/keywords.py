"""Keyword dictionary, per-page scores, evidence, modifiers, and clusters."""

from __future__ import annotations

import json
from typing import Any

from ...database import Database, new_id
from ...job_registry import now_iso

_PAGE_KEYWORD_COLUMNS = (
    "score", "html_score", "content_score", "phrase_score", "site_structure_score",
    "intent_score", "cross_page_score", "rule_boost", "rule_boost_reasons_json",
    "importance", "intent", "intent_group", "commercial_score", "is_primary",
    "title_hit", "h1_hit", "h2_count", "h3_count", "body_count", "anchor_count",
)


class KeywordRepository:
    def __init__(self, db: Database):
        self.db = db

    # -- keyword dictionary (global, cross-run) -----------------------------

    def get_or_create(self, keyword: str, normalized_keyword: str, token_count: int) -> dict[str, Any]:
        existing = self.db.query_one("SELECT * FROM ci_keywords WHERE normalized_keyword=?", (normalized_keyword,))
        if existing:
            return existing
        keyword_id = new_id("cikw_")
        now = now_iso()
        self.db.execute(
            "INSERT INTO ci_keywords (keyword_id, keyword, normalized_keyword, token_count, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?)",
            (keyword_id, keyword, normalized_keyword, token_count, now, now),
        )
        return self.db.query_one("SELECT * FROM ci_keywords WHERE keyword_id=?", (keyword_id,))

    def update_classification(self, keyword_id: str, **fields: Any) -> None:
        allowed = {"branded_type", "is_local", "prefecture", "city", "ward", "station", "keyword_class"}
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"unknown keyword classification field(s): {sorted(unknown)}")
        if not fields:
            return
        set_clause = ", ".join(f"{k}=?" for k in fields)
        self.db.execute(
            f"UPDATE ci_keywords SET {set_clause}, updated_at=? WHERE keyword_id=?",
            (*fields.values(), now_iso(), keyword_id),
        )

    def get(self, keyword_id: str) -> dict[str, Any] | None:
        return self.db.query_one("SELECT * FROM ci_keywords WHERE keyword_id=?", (keyword_id,))

    # -- per-page keyword scores ---------------------------------------------

    def upsert_page_keyword(self, page_id: str, keyword_id: str, crawl_run_id: str, **fields: Any) -> str:
        unknown = set(fields) - set(_PAGE_KEYWORD_COLUMNS)
        if unknown:
            raise ValueError(f"unknown page_keyword field(s): {sorted(unknown)}")
        existing = self.db.query_one(
            "SELECT page_keyword_id FROM ci_page_keywords WHERE page_id=? AND keyword_id=?",
            (page_id, keyword_id),
        )
        now = now_iso()
        if existing:
            page_keyword_id = existing["page_keyword_id"]
            set_clause = ", ".join(f"{k}=?" for k in fields)
            self.db.execute(
                f"UPDATE ci_page_keywords SET {set_clause}, computed_at=? WHERE page_keyword_id=?",
                (*fields.values(), now, page_keyword_id),
            )
            return page_keyword_id

        page_keyword_id = new_id("cipk_")
        columns = ["page_keyword_id", "page_id", "keyword_id", "crawl_run_id", "computed_at", *fields.keys()]
        values = [page_keyword_id, page_id, keyword_id, crawl_run_id, now, *fields.values()]
        self.db.execute(
            f"INSERT INTO ci_page_keywords ({','.join(columns)}) VALUES ({','.join('?' for _ in values)})",
            values,
        )
        return page_keyword_id

    def delete_page_keywords_for_page(self, page_id: str) -> None:
        """Called before re-scoring a page (fresh parse or REANALYZE) so
        stale scores/evidence/modifiers never linger alongside new ones.
        """
        with self.db.transaction() as conn:
            rows = conn.execute("SELECT page_keyword_id FROM ci_page_keywords WHERE page_id=?", (page_id,)).fetchall()
            ids = [r["page_keyword_id"] for r in rows]
            if not ids:
                return
            placeholders = ",".join("?" for _ in ids)
            conn.execute(f"DELETE FROM ci_keyword_occurrences WHERE page_keyword_id IN ({placeholders})", ids)
            conn.execute(f"DELETE FROM ci_keyword_modifiers WHERE page_keyword_id IN ({placeholders})", ids)
            conn.execute("DELETE FROM ci_page_keywords WHERE page_id=?", (page_id,))

    def add_occurrence(
        self, page_keyword_id: str, element_type: str, occurrence_count: int,
        first_position: int | None, weight: float, evidence_text: str | None,
        last_position: int | None = None,
    ) -> None:
        self.db.execute(
            "INSERT INTO ci_keyword_occurrences "
            "(page_keyword_id, element_type, occurrence_count, first_position, last_position, weight, "
            " evidence_text) VALUES (?,?,?,?,?,?,?)",
            (page_keyword_id, element_type, occurrence_count, first_position,
             last_position if last_position is not None else first_position, weight, evidence_text),
        )

    def list_occurrences(self, page_keyword_id: str) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM ci_keyword_occurrences WHERE page_keyword_id=? ORDER BY element_type",
            (page_keyword_id,),
        )

    def add_modifiers(self, page_keyword_id: str, modifiers: list[str]) -> None:
        for m in modifiers:
            self.db.execute(
                "INSERT OR IGNORE INTO ci_keyword_modifiers (page_keyword_id, modifier) VALUES (?,?)",
                (page_keyword_id, m),
            )

    def list_modifiers(self, page_keyword_id: str) -> list[str]:
        rows = self.db.query(
            "SELECT modifier FROM ci_keyword_modifiers WHERE page_keyword_id=?", (page_keyword_id,)
        )
        return [r["modifier"] for r in rows]

    def list_page_keywords_for_page(self, page_id: str) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT pk.*, k.keyword, k.normalized_keyword FROM ci_page_keywords pk "
            "JOIN ci_keywords k ON k.keyword_id = pk.keyword_id "
            "WHERE pk.page_id=? ORDER BY pk.score DESC",
            (page_id,),
        )

    def page_ids_for_keyword_in_run(self, keyword_id: str, crawl_run_id: str) -> list[str]:
        rows = self.db.query(
            "SELECT page_id FROM ci_page_keywords WHERE keyword_id=? AND crawl_run_id=?",
            (keyword_id, crawl_run_id),
        )
        return [r["page_id"] for r in rows]

    # -- run-level keyword listing / detail -----------------------------------

    def list_keywords_for_run(
        self, crawl_run_id: str, limit: int = 200, offset: int = 0,
        importance: str | None = None, intent_group: str | None = None,
        min_commercial_score: int | None = None, branded_type: str | None = None,
        is_local: bool | None = None, keyword_class: str | None = None, q: str | None = None,
    ) -> list[dict[str, Any]]:
        sql = (
            "SELECT k.keyword_id, k.keyword, k.normalized_keyword, k.branded_type, k.is_local, "
            "k.keyword_class, MAX(pk.score) AS score, "
            "(SELECT importance FROM ci_page_keywords WHERE keyword_id=k.keyword_id AND crawl_run_id=? "
            " ORDER BY score DESC LIMIT 1) AS importance, "
            "(SELECT intent FROM ci_page_keywords WHERE keyword_id=k.keyword_id AND crawl_run_id=? "
            " ORDER BY score DESC LIMIT 1) AS intent, "
            "MAX(pk.commercial_score) AS commercial_score, COUNT(DISTINCT pk.page_id) AS page_count, "
            "SUM(pk.is_primary) AS primary_page_count, "
            "(SELECT c.label FROM ci_keyword_clusters c JOIN ci_keyword_cluster_members m "
            " ON m.cluster_id = c.cluster_id WHERE m.keyword_id = k.keyword_id AND c.crawl_run_id=?) AS cluster "
            "FROM ci_keywords k JOIN ci_page_keywords pk ON pk.keyword_id = k.keyword_id "
            "WHERE pk.crawl_run_id=? "
        )
        params: list[Any] = [crawl_run_id, crawl_run_id, crawl_run_id, crawl_run_id]
        if importance:
            sql += " AND pk.importance=?"
            params.append(importance)
        if intent_group:
            sql += " AND pk.intent_group=?"
            params.append(intent_group)
        if min_commercial_score is not None:
            sql += " AND pk.commercial_score >= ?"
            params.append(min_commercial_score)
        if branded_type:
            sql += " AND k.branded_type=?"
            params.append(branded_type)
        if is_local is not None:
            sql += " AND k.is_local=?"
            params.append(1 if is_local else 0)
        if keyword_class:
            sql += " AND k.keyword_class=?"
            params.append(keyword_class)
        if q:
            sql += " AND k.keyword LIKE ?"
            params.append(f"%{q}%")
        sql += " GROUP BY k.keyword_id ORDER BY score DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        return self.db.query(sql, params)

    def get_keyword_detail(self, keyword_id: str, crawl_run_id: str) -> dict[str, Any] | None:
        keyword = self.get(keyword_id)
        if not keyword:
            return None
        page_keywords = self.db.query(
            "SELECT pk.*, p.url, p.title, p.page_type FROM ci_page_keywords pk "
            "JOIN ci_pages p ON p.page_id = pk.page_id "
            "WHERE pk.keyword_id=? AND pk.crawl_run_id=? ORDER BY pk.score DESC",
            (keyword_id, crawl_run_id),
        )
        cluster = self.db.query_one(
            "SELECT c.* FROM ci_keyword_clusters c "
            "JOIN ci_keyword_cluster_members m ON m.cluster_id = c.cluster_id "
            "WHERE m.keyword_id=? AND c.crawl_run_id=?",
            (keyword_id, crawl_run_id),
        )
        return {"keyword": keyword, "page_keywords": page_keywords, "cluster": cluster}


class KeywordClusterRepository:
    def __init__(self, db: Database):
        self.db = db

    def create(self, crawl_run_id: str, label: str, method: str = "shared_head_token") -> str:
        cluster_id = new_id("cicl_")
        self.db.execute(
            "INSERT INTO ci_keyword_clusters (cluster_id, crawl_run_id, label, method, created_at) "
            "VALUES (?,?,?,?,?)",
            (cluster_id, crawl_run_id, label, method, now_iso()),
        )
        return cluster_id

    def add_member(self, cluster_id: str, keyword_id: str) -> None:
        self.db.execute(
            "INSERT OR IGNORE INTO ci_keyword_cluster_members (cluster_id, keyword_id) VALUES (?,?)",
            (cluster_id, keyword_id),
        )

    def clear_for_run(self, crawl_run_id: str) -> None:
        """Clusters are cheap to recompute; REANALYZE / KW-recompute always
        starts from a clean slate for the run rather than merging."""
        with self.db.transaction() as conn:
            rows = conn.execute(
                "SELECT cluster_id FROM ci_keyword_clusters WHERE crawl_run_id=?", (crawl_run_id,)
            ).fetchall()
            ids = [r["cluster_id"] for r in rows]
            if not ids:
                return
            placeholders = ",".join("?" for _ in ids)
            conn.execute(f"DELETE FROM ci_keyword_cluster_members WHERE cluster_id IN ({placeholders})", ids)
            conn.execute(f"DELETE FROM ci_keyword_clusters WHERE crawl_run_id=?", (crawl_run_id,))

    def list_for_run(self, crawl_run_id: str) -> list[dict[str, Any]]:
        return self.db.query("SELECT * FROM ci_keyword_clusters WHERE crawl_run_id=?", (crawl_run_id,))
