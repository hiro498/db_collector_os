"""DB access layer for the viability assessment tool. Same shape as
`candidates.py` / `job_registry.py`: a thin class wrapping `Database`, plain
dict rows in and out, no ORM.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from ..database import Database, new_id


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ViabilityStore:
    def __init__(self, db: Database):
        self.db = db

    # -- db_ideas ----------------------------------------------------------

    def create_idea(self, theme_name: str, category: str | None = None, notes: str | None = None) -> str:
        idea_id = new_id("idea_")
        ts = now_iso()
        self.db.execute(
            """INSERT INTO db_ideas (idea_id, theme_name, category, notes, status, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?)""",
            (idea_id, theme_name, category, notes, "new", ts, ts),
        )
        return idea_id

    def get_idea(self, idea_id: str) -> dict[str, Any] | None:
        return self.db.query_one("SELECT * FROM db_ideas WHERE idea_id=?", (idea_id,))

    def list_ideas(self, status: str | None = None) -> list[dict[str, Any]]:
        if status:
            return self.db.query("SELECT * FROM db_ideas WHERE status=? ORDER BY created_at DESC", (status,))
        return self.db.query("SELECT * FROM db_ideas ORDER BY created_at DESC")

    def set_idea_status(self, idea_id: str, status: str) -> None:
        self.db.execute(
            "UPDATE db_ideas SET status=?, updated_at=? WHERE idea_id=?",
            (status, now_iso(), idea_id),
        )

    # -- evaluation_runs -----------------------------------------------------

    def start_run(self, idea_id: str, phase: str = "phase1", notes: str | None = None) -> str:
        run_id = new_id("run_")
        self.db.execute(
            """INSERT INTO evaluation_runs (run_id, idea_id, phase, status, started_at, notes)
               VALUES (?,?,?,?,?,?)""",
            (run_id, idea_id, phase, "running", now_iso(), notes),
        )
        return run_id

    def set_run_phase(self, run_id: str, phase: str) -> None:
        self.db.execute("UPDATE evaluation_runs SET phase=? WHERE run_id=?", (phase, run_id))

    def finish_run(self, run_id: str, status: str = "completed") -> None:
        self.db.execute(
            "UPDATE evaluation_runs SET status=?, finished_at=? WHERE run_id=?",
            (status, now_iso(), run_id),
        )

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        return self.db.query_one("SELECT * FROM evaluation_runs WHERE run_id=?", (run_id,))

    def list_runs(self, idea_id: str) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM evaluation_runs WHERE idea_id=? ORDER BY started_at DESC", (idea_id,)
        )

    def latest_run(self, idea_id: str) -> dict[str, Any] | None:
        return self.db.query_one(
            "SELECT * FROM evaluation_runs WHERE idea_id=? ORDER BY started_at DESC LIMIT 1", (idea_id,)
        )

    # -- keyword_candidates --------------------------------------------------

    def add_keyword_candidate(
        self, idea_id: str, keyword: str, is_main: bool = False, axis: dict[str, Any] | None = None
    ) -> tuple[str, bool]:
        """Insert unless (idea_id, keyword) already exists. Returns (candidate_id, created)."""
        existing = self.db.query_one(
            "SELECT candidate_id FROM keyword_candidates WHERE idea_id=? AND keyword=?", (idea_id, keyword)
        )
        if existing:
            return existing["candidate_id"], False
        candidate_id = new_id("kwc_")
        self.db.execute(
            """INSERT INTO keyword_candidates (candidate_id, idea_id, keyword, is_main, axis_json, created_at)
               VALUES (?,?,?,?,?,?)""",
            (candidate_id, idea_id, keyword, 1 if is_main else 0, json.dumps(axis or {}, ensure_ascii=False), now_iso()),
        )
        return candidate_id, True

    def list_keyword_candidates(self, idea_id: str) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM keyword_candidates WHERE idea_id=? ORDER BY is_main DESC, created_at", (idea_id,)
        )

    def get_keyword_candidate_by_keyword(self, idea_id: str, keyword: str) -> dict[str, Any] | None:
        return self.db.query_one(
            "SELECT * FROM keyword_candidates WHERE idea_id=? AND keyword=?", (idea_id, keyword)
        )

    # -- keyword_metrics -------------------------------------------------------

    def add_keyword_metric(
        self,
        candidate_id: str,
        source: str,
        monthly_search_volume: int | None,
        run_id: str | None = None,
        competition: float | None = None,
        low_bid: float | None = None,
        high_bid: float | None = None,
        trend: str | None = None,
        collected_at: str | None = None,
    ) -> int:
        cur = self.db.execute(
            """INSERT INTO keyword_metrics
               (candidate_id, run_id, monthly_search_volume, source, competition, low_bid, high_bid, trend, collected_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                candidate_id, run_id, monthly_search_volume, source, competition, low_bid, high_bid, trend,
                collected_at or now_iso(),
            ),
        )
        return cur.lastrowid

    def latest_metric_for_candidate(self, candidate_id: str) -> dict[str, Any] | None:
        return self.db.query_one(
            "SELECT * FROM keyword_metrics WHERE candidate_id=? ORDER BY collected_at DESC, metric_id DESC LIMIT 1",
            (candidate_id,),
        )

    def latest_metrics_for_idea(self, idea_id: str) -> list[dict[str, Any]]:
        """One row per keyword candidate: the candidate joined with its most
        recently collected metric (any source, any run). Candidates with no
        metric yet are included with volume fields NULL.
        """
        return self.db.query(
            """
            SELECT c.candidate_id, c.keyword, c.is_main, c.axis_json,
                   m.monthly_search_volume, m.source, m.competition, m.low_bid, m.high_bid,
                   m.trend, m.collected_at
            FROM keyword_candidates c
            LEFT JOIN (
                SELECT km1.*
                FROM keyword_metrics km1
                JOIN (
                    SELECT candidate_id, MAX(collected_at) AS max_collected_at
                    FROM keyword_metrics GROUP BY candidate_id
                ) latest
                  ON km1.candidate_id = latest.candidate_id
                 AND km1.collected_at = latest.max_collected_at
            ) m ON m.candidate_id = c.candidate_id
            WHERE c.idea_id = ?
            ORDER BY c.is_main DESC, c.created_at
            """,
            (idea_id,),
        )

    # -- demand_summaries --------------------------------------------------

    def save_demand_summary(self, run_id: str, idea_id: str, summary: dict[str, Any]) -> str:
        summary_id = new_id("dsum_")
        self.db.execute(
            """INSERT INTO demand_summaries
               (summary_id, run_id, idea_id, total_search_volume, main_kw_volume, longtail_kw_count,
                kw_with_volume_count, kw_zero_or_low_count, dispersion, top_keywords_json,
                phase1_result, reasoning, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                summary_id, run_id, idea_id,
                summary["total_search_volume"], summary["main_kw_volume"], summary["longtail_kw_count"],
                summary["kw_with_volume_count"], summary["kw_zero_or_low_count"], summary.get("dispersion"),
                json.dumps(summary.get("top_keywords", []), ensure_ascii=False),
                summary["phase1_result"], summary["reasoning"], now_iso(),
            ),
        )
        return summary_id

    def get_demand_summary(self, run_id: str) -> dict[str, Any] | None:
        return self.db.query_one("SELECT * FROM demand_summaries WHERE run_id=?", (run_id,))

    # -- serp_queries / serp_results -----------------------------------------

    def add_serp_query(self, run_id: str, candidate_id: str, query_text: str, source: str) -> str:
        query_id = new_id("sq_")
        self.db.execute(
            """INSERT INTO serp_queries (query_id, run_id, candidate_id, query_text, source, collected_at)
               VALUES (?,?,?,?,?,?)""",
            (query_id, run_id, candidate_id, query_text, source, now_iso()),
        )
        return query_id

    def add_serp_result(self, query_id: str, result: dict[str, Any]) -> int:
        cur = self.db.execute(
            """INSERT INTO serp_results
               (query_id, rank, title, url, domain, snippet, site_type, page_type, title_match,
                db_type_page, intent_satisfied, collected_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                query_id, result["rank"], result.get("title"), result.get("url"), result.get("domain"),
                result.get("snippet"), result.get("site_type"), result.get("page_type"), result.get("title_match"),
                result.get("db_type_page"), result.get("intent_satisfied"), result.get("collected_at") or now_iso(),
            ),
        )
        return cur.lastrowid

    def list_serp_queries_for_run(self, run_id: str) -> list[dict[str, Any]]:
        return self.db.query("SELECT * FROM serp_queries WHERE run_id=? ORDER BY collected_at", (run_id,))

    def list_serp_results(self, query_id: str) -> list[dict[str, Any]]:
        return self.db.query("SELECT * FROM serp_results WHERE query_id=? ORDER BY rank", (query_id,))

    # -- keyword_competition --------------------------------------------------

    def save_keyword_competition(
        self, run_id: str, candidate_id: str, query_id: str, result: dict[str, Any]
    ) -> str:
        competition_id = new_id("kwcp_")
        self.db.execute(
            """INSERT INTO keyword_competition
               (competition_id, run_id, candidate_id, query_id, strength, strength_score,
                intent_satisfied, db_type_page_present, site_type_summary_json, reasoning, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                competition_id, run_id, candidate_id, query_id, result["strength"], result["strength_score"],
                1 if result.get("intent_satisfied") else 0, 1 if result.get("db_type_page_present") else 0,
                json.dumps(result.get("site_type_summary", {}), ensure_ascii=False), result["reasoning"], now_iso(),
            ),
        )
        return competition_id

    def list_keyword_competition_for_run(self, run_id: str) -> list[dict[str, Any]]:
        return self.db.query(
            """SELECT kc.*, cand.keyword, cand.is_main
               FROM keyword_competition kc
               JOIN keyword_candidates cand ON cand.candidate_id = kc.candidate_id
               WHERE kc.run_id=?""",
            (run_id,),
        )

    # -- db_idea_evaluations --------------------------------------------------

    def save_evaluation(self, run_id: str, idea_id: str, evaluation: dict[str, Any]) -> str:
        evaluation_id = new_id("eval_")
        self.db.execute(
            """INSERT INTO db_idea_evaluations
               (evaluation_id, run_id, idea_id, demand_score, competition_score, db_fit_score, priority_score,
                weak_ratio, medium_ratio, strong_ratio, winnable_demand, unwinnable_demand,
                final_judgement, reasoning, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                evaluation_id, run_id, idea_id,
                evaluation["demand_score"], evaluation["competition_score"], evaluation["db_fit_score"],
                evaluation["priority_score"], evaluation.get("weak_ratio"), evaluation.get("medium_ratio"),
                evaluation.get("strong_ratio"), evaluation.get("winnable_demand"), evaluation.get("unwinnable_demand"),
                evaluation["final_judgement"], evaluation["reasoning"], now_iso(),
            ),
        )
        return evaluation_id

    def get_evaluation_for_run(self, run_id: str) -> dict[str, Any] | None:
        return self.db.query_one("SELECT * FROM db_idea_evaluations WHERE run_id=?", (run_id,))

    def list_evaluations_for_idea(self, idea_id: str) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM db_idea_evaluations WHERE idea_id=? ORDER BY created_at DESC", (idea_id,)
        )
