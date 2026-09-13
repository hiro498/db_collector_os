"""Schema-only persistence for P1+ extension points (SERP / Opportunity /
shared term dictionary). No engine in this package writes to these tables
yet -- see competitive_intelligence/future/ for why. These CRUD helpers
exist purely so the tables are reachable without a schema change once that
logic is built, per spec section 46 ("future extensions must not be blocked
by the DB/interface design").
"""

from __future__ import annotations

from typing import Any

from ...database import Database, new_id
from ...job_registry import now_iso


class SerpRepository:
    def __init__(self, db: Database):
        self.db = db

    def create_query(self, domain_id: str, query_text: str, keyword_id: str | None = None) -> str:
        serp_query_id = new_id("ciserpq_")
        self.db.execute(
            "INSERT INTO ci_serp_queries (serp_query_id, domain_id, keyword_id, query_text, status) "
            "VALUES (?,?,?,?,'not_implemented')",
            (serp_query_id, domain_id, keyword_id, query_text),
        )
        return serp_query_id

    def list_for_domain(self, domain_id: str) -> list[dict[str, Any]]:
        return self.db.query("SELECT * FROM ci_serp_queries WHERE domain_id=?", (domain_id,))


class OpportunityRepository:
    def __init__(self, db: Database):
        self.db = db

    def create(self, domain_id: str, keyword_id: str | None = None) -> str:
        opportunity_id = new_id("ciopp_")
        self.db.execute(
            "INSERT INTO ci_opportunities (opportunity_id, domain_id, keyword_id, status, created_at) "
            "VALUES (?,?,?,'not_implemented',?)",
            (opportunity_id, domain_id, keyword_id, now_iso()),
        )
        return opportunity_id

    def list_for_domain(self, domain_id: str) -> list[dict[str, Any]]:
        return self.db.query("SELECT * FROM ci_opportunities WHERE domain_id=?", (domain_id,))


class TermDictionaryRepository:
    def __init__(self, db: Database):
        self.db = db

    def get_by_term(self, term: str) -> dict[str, Any] | None:
        return self.db.query_one("SELECT * FROM ci_term_dictionary WHERE term=?", (term,))

    def list_by_type(self, term_type: str) -> list[dict[str, Any]]:
        return self.db.query("SELECT * FROM ci_term_dictionary WHERE term_type=?", (term_type,))
