"""Orchestrates the full Phase 1 -> Phase 2 -> scoring -> judgement flow on
top of ViabilityStore. Every step that produces numbers records which
run_id it belongs to, so re-investigating a theme later never overwrites
history (spec section 9): call `start_run` again and the old run's rows are
untouched.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from ..database import Database
from .competition_analysis import score_keyword_competition, summarize_theme_competition
from .config import ViabilityConfig, load_viability_config
from .demand_analysis import summarize_demand
from .keyword_axes import AXES
from .keyword_generator import generate_candidates
from .keyword_sources.base import KeywordSource
from .keyword_sources.csv_import import CsvKeywordSource
from .scoring import compute_competition_score, compute_db_fit_score, compute_demand_score, compute_priority_score
from .serp_sources.base import SerpSource
from .serp_sources.csv_import import CsvSerpSource
from .store import ViabilityStore


class Phase1NotPassedError(RuntimeError):
    """Raised by run_phase2()/finalize_evaluation() shortcuts when called on
    a run whose Phase 1 demand gate failed -- Phase 2 must never spend
    effort investigating a theme already decided NO-GO."""


class EvaluationRunner:
    def __init__(self, db: Database, config: ViabilityConfig | None = None):
        self.db = db
        self.store = ViabilityStore(db)
        self.config = config or load_viability_config()

    # -- idea / candidate setup ---------------------------------------------

    def create_idea(self, theme_name: str, category: str | None = None, notes: str | None = None) -> str:
        return self.store.create_idea(theme_name, category, notes)

    def add_keywords_from_generator(
        self,
        idea_id: str,
        main_keywords: list[str],
        axes: dict[str, list[str]] | None = None,
        combos: list[list[str]] | None = None,
    ) -> list[str]:
        specs = generate_candidates(main_keywords, axes, combos)
        candidate_ids = []
        for spec in specs:
            cid, _ = self.store.add_keyword_candidate(idea_id, spec.keyword, spec.is_main, spec.axis)
            candidate_ids.append(cid)
        return candidate_ids

    def add_keywords_from_csv(self, idea_id: str, csv_path: str | Path) -> list[str]:
        """Columns: keyword (required), is_main (true/false, optional),
        axis_type (optional, one of keyword_axes.AXES), axis_value (optional)."""
        candidate_ids = []
        with open(csv_path, encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                keyword = (row.get("keyword") or "").strip()
                if not keyword:
                    continue
                is_main = (row.get("is_main") or "").strip().lower() in ("1", "true", "yes")
                axis_type = (row.get("axis_type") or "").strip()
                axis_value = (row.get("axis_value") or "").strip()
                axis = {axis_type: axis_value} if axis_type and axis_value else {}
                cid, _ = self.store.add_keyword_candidate(idea_id, keyword, is_main, axis)
                candidate_ids.append(cid)
        return candidate_ids

    # -- Phase 1: demand ------------------------------------------------------

    def import_keyword_metrics(
        self, idea_id: str, source: KeywordSource, run_id: str | None = None, source_label: str | None = None
    ) -> int:
        """Pull metrics for every known candidate of this idea from `source`
        (any KeywordSource -- CSV import today) and record them. Unknown
        keywords the source returns (not yet a tracked candidate) are added
        as non-main candidates so nothing collected is silently dropped.
        """
        candidates = self.store.list_keyword_candidates(idea_id)
        known_keywords = {c["keyword"] for c in candidates}
        records = source.fetch(list(known_keywords) or None)

        count = 0
        for record in records:
            candidate = self.store.get_keyword_candidate_by_keyword(idea_id, record.keyword)
            if candidate is None:
                candidate_id, _ = self.store.add_keyword_candidate(idea_id, record.keyword, is_main=False)
            else:
                candidate_id = candidate["candidate_id"]
            self.store.add_keyword_metric(
                candidate_id=candidate_id,
                source=source_label or record.source,
                monthly_search_volume=record.monthly_search_volume,
                run_id=run_id,
                competition=record.competition,
                low_bid=record.low_bid,
                high_bid=record.high_bid,
                trend=record.trend,
            )
            count += 1
        return count

    def import_keyword_metrics_csv(
        self, idea_id: str, csv_path: str | Path, run_id: str | None = None, source_label: str = "csv_import"
    ) -> int:
        return self.import_keyword_metrics(idea_id, CsvKeywordSource(csv_path), run_id=run_id, source_label=source_label)

    def run_phase1(self, idea_id: str, run_id: str | None = None) -> tuple[dict[str, Any], str]:
        if run_id is None:
            run_id = self.store.start_run(idea_id, phase="phase1")
        self.store.set_idea_status(idea_id, "evaluating")

        rows = self.store.latest_metrics_for_idea(idea_id)
        summary = summarize_demand(rows, self.config)
        self.store.save_demand_summary(run_id, idea_id, summary)

        if summary["phase1_result"] != "PASS":
            self.store.set_idea_status(idea_id, "no_go")
            self.store.finish_run(run_id, status="completed")
        else:
            self.store.set_run_phase(run_id, "phase1_passed")

        return summary, run_id

    # -- Phase 2: competition ---------------------------------------------

    def import_serp_results(self, run_id: str, idea_id: str, source: SerpSource) -> int:
        run = self.store.get_run(run_id)
        if run is None:
            raise ValueError(f"no such run: {run_id}")
        demand_summary = self.store.get_demand_summary(run_id)
        if demand_summary is None or demand_summary["phase1_result"] != "PASS":
            raise Phase1NotPassedError(
                f"run {run_id} has not passed Phase 1 -- refusing to spend Phase 2 effort on it."
            )

        candidates = self.store.list_keyword_candidates(idea_id)
        count = 0
        for candidate in candidates:
            result = source.search(candidate["keyword"])
            if not result.results:
                continue
            query_id = self.store.add_serp_query(run_id, candidate["candidate_id"], candidate["keyword"], result.source)
            for r in result.results:
                self.store.add_serp_result(
                    query_id,
                    {
                        "rank": r.rank, "title": r.title, "url": r.url, "domain": r.domain, "snippet": r.snippet,
                        "site_type": r.site_type, "page_type": r.page_type, "title_match": r.title_match,
                        "db_type_page": r.db_type_page, "intent_satisfied": r.intent_satisfied,
                    },
                )
            count += 1
        return count

    def import_serp_results_csv(self, run_id: str, idea_id: str, csv_path: str | Path, source_label: str = "csv_import") -> int:
        return self.import_serp_results(run_id, idea_id, CsvSerpSource(csv_path, default_source=source_label))

    def run_phase2(self, run_id: str) -> dict[str, Any]:
        self.store.set_run_phase(run_id, "phase2")
        queries = self.store.list_serp_queries_for_run(run_id)
        for query in queries:
            results = self.store.list_serp_results(query["query_id"])
            scored = score_keyword_competition(query["query_text"], results, self.config)
            self.store.save_keyword_competition(run_id, query["candidate_id"], query["query_id"], scored)

        competition_rows = self.store.list_keyword_competition_for_run(run_id)
        idea_id = self.store.get_run(run_id)["idea_id"]
        volume_by_candidate = {
            r["candidate_id"]: r.get("monthly_search_volume") or 0
            for r in self.store.latest_metrics_for_idea(idea_id)
        }
        return summarize_theme_competition(competition_rows, volume_by_candidate)

    # -- finalize -----------------------------------------------------------

    def finalize_evaluation(self, run_id: str) -> dict[str, Any]:
        from .judgement import decide_final_judgement

        run = self.store.get_run(run_id)
        idea_id = run["idea_id"]
        demand_summary = self.store.get_demand_summary(run_id)
        if demand_summary is None:
            raise ValueError(f"run {run_id} has no demand summary -- call run_phase1() first")

        candidates = self.store.list_keyword_candidates(idea_id)
        import json as _json

        axis_keys: set[str] = set()
        for c in candidates:
            axis_keys.update(k for k in _json.loads(c["axis_json"]).keys() if k in AXES)

        competition_rows = self.store.list_keyword_competition_for_run(run_id)
        if competition_rows:
            volume_by_candidate = {
                r["candidate_id"]: r.get("monthly_search_volume") or 0
                for r in self.store.latest_metrics_for_idea(idea_id)
            }
            competition_summary = summarize_theme_competition(competition_rows, volume_by_candidate)
        else:
            competition_summary = {"weak_ratio": None, "medium_ratio": None, "strong_ratio": None, "winnable_demand": 0, "unwinnable_demand": 0}

        demand_score = compute_demand_score(demand_summary, self.config)
        competition_score = compute_competition_score(competition_summary, self.config)
        db_fit_score = compute_db_fit_score(demand_summary, len(axis_keys), len(candidates), self.config)
        priority_score = compute_priority_score(demand_score, competition_score, db_fit_score, self.config)

        judgement, reasoning = decide_final_judgement(
            demand_summary["phase1_result"], competition_summary,
            demand_score, competition_score, db_fit_score, priority_score, self.config,
        )

        evaluation = {
            "demand_score": demand_score, "competition_score": competition_score, "db_fit_score": db_fit_score,
            "priority_score": priority_score, **competition_summary,
            "final_judgement": judgement, "reasoning": reasoning,
        }
        self.store.save_evaluation(run_id, idea_id, evaluation)
        self.store.set_idea_status(idea_id, {"GO": "go", "HOLD": "hold", "NO-GO": "no_go"}[judgement])
        self.store.finish_run(run_id, status="completed")
        return evaluation
