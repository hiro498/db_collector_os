"""Page / page-element persistence."""

from __future__ import annotations

import json
from typing import Any

from ...database import Database, new_id
from ...job_registry import now_iso


class PageRepository:
    def __init__(self, db: Database):
        self.db = db

    def upsert(
        self,
        crawl_url_id: str,
        crawl_run_id: str,
        domain_id: str,
        url: str,
        normalized_url: str,
        fetched_at: str,
        **fields: Any,
    ) -> str:
        """One page row per crawl_url. Re-running analysis for the same
        crawl_url (REANALYZE, section 45) updates the existing row in place
        rather than creating a duplicate.
        """
        existing = self.db.query_one("SELECT page_id FROM ci_pages WHERE crawl_url_id=?", (crawl_url_id,))
        now = now_iso()
        allowed = {
            "title", "meta_description", "meta_keywords", "canonical_url", "robots_meta",
            "page_type", "page_type_confidence", "analysis_target", "monetization_type",
            "monetization_score", "published_at", "updated_at_source", "raw_html_hash", "analyzed_at",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"unknown page field(s): {sorted(unknown)}")

        if existing:
            page_id = existing["page_id"]
            if fields:
                set_clause = ", ".join(f"{k}=?" for k in fields)
                self.db.execute(
                    f"UPDATE ci_pages SET {set_clause}, updated_at=? WHERE page_id=?",
                    (*fields.values(), now, page_id),
                )
            return page_id

        page_id = new_id("cipage_")
        columns = ["page_id", "crawl_url_id", "crawl_run_id", "domain_id", "url", "normalized_url",
                   "fetched_at", "created_at", "updated_at", *fields.keys()]
        values = [page_id, crawl_url_id, crawl_run_id, domain_id, url, normalized_url,
                  fetched_at, now, now, *fields.values()]
        placeholders = ",".join("?" for _ in values)
        self.db.execute(
            f"INSERT INTO ci_pages ({','.join(columns)}) VALUES ({placeholders})", values
        )
        return page_id

    def get(self, page_id: str) -> dict[str, Any] | None:
        return self.db.query_one("SELECT * FROM ci_pages WHERE page_id=?", (page_id,))

    def get_by_crawl_url(self, crawl_url_id: str) -> dict[str, Any] | None:
        return self.db.query_one("SELECT * FROM ci_pages WHERE crawl_url_id=?", (crawl_url_id,))

    def list_for_run(
        self, crawl_run_id: str, limit: int = 200, offset: int = 0,
        page_type: str | None = None, analysis_target: bool | None = None, q: str | None = None,
        indexable: bool | None = None, monetization_type: str | None = None, min_score: int | None = None,
    ) -> list[dict[str, Any]]:
        sql = (
            "SELECT p.*, "
            " (SELECT k.keyword FROM ci_page_keywords pk JOIN ci_keywords k ON k.keyword_id = pk.keyword_id "
            "  WHERE pk.page_id = p.page_id AND pk.is_primary=1 LIMIT 1) AS primary_keyword, "
            " (SELECT pk.score FROM ci_page_keywords pk WHERE pk.page_id = p.page_id AND pk.is_primary=1 LIMIT 1) "
            "  AS primary_keyword_score, "
            " (SELECT pk.intent FROM ci_page_keywords pk WHERE pk.page_id = p.page_id AND pk.is_primary=1 LIMIT 1) "
            "  AS primary_keyword_intent "
            "FROM ci_pages p WHERE crawl_run_id=?"
        )
        params: list[Any] = [crawl_run_id]
        if page_type:
            sql += " AND page_type=?"
            params.append(page_type)
        if analysis_target is not None:
            sql += " AND analysis_target=?"
            params.append(1 if analysis_target else 0)
        if q:
            sql += " AND (url LIKE ? OR title LIKE ?)"
            params.extend([f"%{q}%", f"%{q}%"])
        if indexable is not None:
            sql += " AND (robots_meta IS NULL OR robots_meta NOT LIKE '%noindex%')" if indexable \
                else " AND robots_meta LIKE '%noindex%'"
        if monetization_type:
            sql += " AND monetization_type=?"
            params.append(monetization_type)
        if min_score is not None:
            sql += (
                " AND page_id IN (SELECT page_id FROM ci_page_keywords WHERE is_primary=1 AND score >= ?)"
            )
            params.append(min_score)
        sql += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        return self.db.query(sql, params)

    def count_for_run(self, crawl_run_id: str) -> int:
        row = self.db.query_one("SELECT COUNT(*) AS n FROM ci_pages WHERE crawl_run_id=?", (crawl_run_id,))
        return row["n"] if row else 0

    def analyzed_count_for_run(self, crawl_run_id: str) -> int:
        row = self.db.query_one(
            "SELECT COUNT(*) AS n FROM ci_pages WHERE crawl_run_id=? AND analysis_target=1", (crawl_run_id,)
        )
        return row["n"] if row else 0


class PageElementRepository:
    def __init__(self, db: Database):
        self.db = db

    def replace_all(self, page_id: str, elements: list[dict[str, Any]]) -> None:
        """Replaces every element row for a page -- used both on first parse
        and on REANALYZE-driven re-parses, so stale elements never linger.
        """
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM ci_page_elements WHERE page_id=?", (page_id,))
            for pos, el in enumerate(elements):
                conn.execute(
                    "INSERT INTO ci_page_elements (page_id, element_type, position, text, attrs_json) "
                    "VALUES (?,?,?,?,?)",
                    (page_id, el["element_type"], el.get("position", pos), el.get("text"),
                     json.dumps(el.get("attrs", {}), ensure_ascii=False)),
                )

    def list_for_page(self, page_id: str, element_type: str | None = None) -> list[dict[str, Any]]:
        if element_type:
            return self.db.query(
                "SELECT * FROM ci_page_elements WHERE page_id=? AND element_type=? ORDER BY position",
                (page_id, element_type),
            )
        return self.db.query("SELECT * FROM ci_page_elements WHERE page_id=? ORDER BY position", (page_id,))

    def list_for_run(self, crawl_run_id: str) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT pe.* FROM ci_page_elements pe JOIN ci_pages p ON p.page_id = pe.page_id "
            "WHERE p.crawl_run_id=?",
            (crawl_run_id,),
        )

    def mark_boilerplate(self, page_element_ids: list[int]) -> None:
        if not page_element_ids:
            return
        placeholders = ",".join("?" for _ in page_element_ids)
        self.db.execute(
            f"UPDATE ci_page_elements SET is_boilerplate=1 WHERE page_element_id IN ({placeholders})",
            page_element_ids,
        )
