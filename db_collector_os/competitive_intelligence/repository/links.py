"""Internal links, outbound links, and CTAs."""

from __future__ import annotations

from typing import Any

from ...database import Database


class InternalLinkRepository:
    def __init__(self, db: Database):
        self.db = db

    def replace_for_page(self, crawl_run_id: str, source_page_id: str, links: list[dict[str, Any]]) -> None:
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM ci_internal_links WHERE source_page_id=?", (source_page_id,))
            for pos, link in enumerate(links):
                conn.execute(
                    "INSERT INTO ci_internal_links "
                    "(crawl_run_id, source_page_id, target_url, anchor_text, position, nofollow) "
                    "VALUES (?,?,?,?,?,?)",
                    (crawl_run_id, source_page_id, link["target_url"], link.get("anchor_text"),
                     link.get("position", pos), 1 if link.get("nofollow") else 0),
                )

    def resolve_targets(self, crawl_run_id: str) -> None:
        """Best-effort fills target_page_id once the target URL's page row
        exists. Internal links are stored before every page in the run has
        necessarily been fetched, so this is re-run after each crawl batch.
        """
        self.db.execute(
            "UPDATE ci_internal_links SET target_page_id = ("
            "  SELECT p.page_id FROM ci_pages p WHERE p.crawl_run_id = ci_internal_links.crawl_run_id "
            "  AND p.normalized_url = ci_internal_links.target_url"
            ") WHERE crawl_run_id=? AND target_page_id IS NULL",
            (crawl_run_id,),
        )

    def inbound_count_by_page(self, crawl_run_id: str) -> dict[str, int]:
        rows = self.db.query(
            "SELECT target_page_id, COUNT(*) AS n FROM ci_internal_links "
            "WHERE crawl_run_id=? AND target_page_id IS NOT NULL GROUP BY target_page_id",
            (crawl_run_id,),
        )
        return {r["target_page_id"]: r["n"] for r in rows}

    def outbound_count_by_page(self, crawl_run_id: str) -> dict[str, int]:
        rows = self.db.query(
            "SELECT source_page_id, COUNT(*) AS n FROM ci_internal_links WHERE crawl_run_id=? "
            "GROUP BY source_page_id",
            (crawl_run_id,),
        )
        return {r["source_page_id"]: r["n"] for r in rows}

    def list_for_run(self, crawl_run_id: str) -> list[dict[str, Any]]:
        return self.db.query("SELECT * FROM ci_internal_links WHERE crawl_run_id=?", (crawl_run_id,))


class OutboundLinkRepository:
    def __init__(self, db: Database):
        self.db = db

    def replace_for_page(self, crawl_run_id: str, source_page_id: str, links: list[dict[str, Any]]) -> None:
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM ci_outbound_links WHERE source_page_id=?", (source_page_id,))
            for pos, link in enumerate(links):
                conn.execute(
                    "INSERT INTO ci_outbound_links "
                    "(crawl_run_id, source_page_id, url, target_domain, anchor_text, link_type, "
                    " affiliate_network, merchant, position) VALUES (?,?,?,?,?,?,?,?,?)",
                    (crawl_run_id, source_page_id, link["url"], link["target_domain"], link.get("anchor_text"),
                     link.get("link_type", "other"), link.get("affiliate_network"), link.get("merchant"),
                     link.get("position", pos)),
                )

    def list_for_page(self, page_id: str) -> list[dict[str, Any]]:
        return self.db.query("SELECT * FROM ci_outbound_links WHERE source_page_id=?", (page_id,))

    def affiliate_count_by_page(self, crawl_run_id: str) -> dict[str, int]:
        rows = self.db.query(
            "SELECT source_page_id, COUNT(*) AS n FROM ci_outbound_links "
            "WHERE crawl_run_id=? AND link_type='affiliate' GROUP BY source_page_id",
            (crawl_run_id,),
        )
        return {r["source_page_id"]: r["n"] for r in rows}


class CtaRepository:
    def __init__(self, db: Database):
        self.db = db

    def replace_for_page(self, page_id: str, ctas: list[dict[str, Any]]) -> None:
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM ci_ctas WHERE page_id=?", (page_id,))
            for pos, cta in enumerate(ctas):
                conn.execute(
                    "INSERT INTO ci_ctas "
                    "(page_id, cta_text, target_url, target_domain, cta_type, position, affiliate_detected) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (page_id, cta.get("cta_text"), cta.get("target_url"), cta.get("target_domain"),
                     cta.get("cta_type", "other"), cta.get("position", pos),
                     1 if cta.get("affiliate_detected") else 0),
                )

    def list_for_page(self, page_id: str) -> list[dict[str, Any]]:
        return self.db.query("SELECT * FROM ci_ctas WHERE page_id=?", (page_id,))

    def count_by_page(self, crawl_run_id: str) -> dict[str, int]:
        rows = self.db.query(
            "SELECT c.page_id, COUNT(*) AS n FROM ci_ctas c JOIN ci_pages p ON p.page_id = c.page_id "
            "WHERE p.crawl_run_id=? GROUP BY c.page_id",
            (crawl_run_id,),
        )
        return {r["page_id"]: r["n"] for r in rows}
