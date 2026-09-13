"""Per-domain site-level aggregation (section 10 of the crawl-completion
checklist: "site aggregation done")."""

from __future__ import annotations

from typing import Any

from ...database import Database
from ...job_registry import now_iso


class SiteProfileRepository:
    def __init__(self, db: Database):
        self.db = db

    def upsert(self, domain_id: str, crawl_run_id: str, **fields: Any) -> None:
        allowed = {"total_pages", "analyzed_pages", "total_keywords", "commercial_keyword_count"}
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"unknown site profile field(s): {sorted(unknown)}")
        now = now_iso()
        existing = self.db.query_one("SELECT domain_id FROM ci_site_profiles WHERE domain_id=?", (domain_id,))
        if existing:
            set_clause = ", ".join(f"{k}=?" for k in fields)
            self.db.execute(
                f"UPDATE ci_site_profiles SET crawl_run_id=?, {set_clause}, updated_at=? WHERE domain_id=?",
                (crawl_run_id, *fields.values(), now, domain_id),
            )
            return
        columns = ["domain_id", "crawl_run_id", "updated_at", *fields.keys()]
        values = [domain_id, crawl_run_id, now, *fields.values()]
        self.db.execute(
            f"INSERT INTO ci_site_profiles ({','.join(columns)}) VALUES ({','.join('?' for _ in values)})",
            values,
        )

    def get(self, domain_id: str) -> dict[str, Any] | None:
        return self.db.query_one("SELECT * FROM ci_site_profiles WHERE domain_id=?", (domain_id,))
