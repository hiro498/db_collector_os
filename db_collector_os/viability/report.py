"""Final report (spec section 10): one theme's demand + competition +
scores + judgement + human-readable reasoning, built from whatever a given
run recorded in the DB.
"""

from __future__ import annotations

import json
from typing import Any

from .store import ViabilityStore


def build_report(store: ViabilityStore, idea_id: str, run_id: str | None = None) -> dict[str, Any]:
    idea = store.get_idea(idea_id)
    if idea is None:
        raise ValueError(f"no such idea: {idea_id}")

    run = store.get_run(run_id) if run_id else store.latest_run(idea_id)
    if run is None:
        raise ValueError(f"idea {idea_id} has no evaluation runs yet")
    run_id = run["run_id"]

    demand_summary = store.get_demand_summary(run_id)
    evaluation = store.get_evaluation_for_run(run_id)

    report: dict[str, Any] = {
        "theme_name": idea["theme_name"],
        "idea_id": idea_id,
        "run_id": run_id,
        "run_started_at": run["started_at"],
    }

    if demand_summary is None:
        report["demand_result"] = None
        return report

    report.update(
        {
            "demand_result": demand_summary["phase1_result"],
            "total_search_volume": demand_summary["total_search_volume"],
            "kw_with_volume_count": demand_summary["kw_with_volume_count"],
            "kw_zero_or_low_count": demand_summary["kw_zero_or_low_count"],
            "longtail_kw_count": demand_summary["longtail_kw_count"],
            "top_keywords": json.loads(demand_summary["top_keywords_json"]),
            "dispersion": demand_summary["dispersion"],
            "demand_reasoning": demand_summary["reasoning"],
        }
    )

    if evaluation is None:
        return report

    report.update(
        {
            "weak_ratio": evaluation["weak_ratio"],
            "medium_ratio": evaluation["medium_ratio"],
            "strong_ratio": evaluation["strong_ratio"],
            "winnable_demand": evaluation["winnable_demand"],
            "unwinnable_demand": evaluation["unwinnable_demand"],
            "demand_score": evaluation["demand_score"],
            "competition_score": evaluation["competition_score"],
            "db_fit_score": evaluation["db_fit_score"],
            "priority_score": evaluation["priority_score"],
            "final_judgement": evaluation["final_judgement"],
            "judgement_reasoning": evaluation["reasoning"],
        }
    )
    return report


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value:.0%}"


def render_text(report: dict[str, Any]) -> str:
    lines = [f"テーマ名: {report['theme_name']}"]

    demand_result = report.get("demand_result")
    if demand_result is None:
        lines.append("需要判定: (未実施 -- Phase 1 未実行)")
        return "\n".join(lines)

    lines.append(f"需要判定: {demand_result}")
    lines.append(f"総月間検索需要: {report['total_search_volume']}")
    lines.append(f"検索需要ありKW: {report['kw_with_volume_count']}件")

    top_keywords = report.get("top_keywords") or []
    if top_keywords:
        lines.append("主要KW:")
        for kw in top_keywords[:5]:
            lines.append(f"  {kw['keyword']} / {kw['monthly_search_volume']}")

    lines.append(f"ロングテール: {report['longtail_kw_count']}件")

    if "final_judgement" not in report:
        lines.append("競合: (未実施 -- Phase 2 未実行)")
        lines.append(f"最終判定: {'NO-GO' if demand_result == 'FAIL' else '(未確定)'}")
        lines.append(f"判定理由: {report['demand_reasoning']}")
        return "\n".join(lines)

    lines.append(
        "競合: WEAK {} / MEDIUM {} / STRONG {}".format(
            _pct(report.get("weak_ratio")), _pct(report.get("medium_ratio")), _pct(report.get("strong_ratio"))
        )
    )
    lines.append(f"攻略可能推定検索需要: {report['winnable_demand']}/月")
    lines.append(f"Demand Score: {report['demand_score']}/100")
    lines.append(f"Competition Score: {report['competition_score']}/100")
    lines.append(f"DB Fit Score: {report['db_fit_score']}/100")
    lines.append(f"Priority Score: {report['priority_score']}/100")
    lines.append(f"最終判定: {report['final_judgement']}")
    lines.append(f"判定理由: {report['judgement_reasoning']}")
    return "\n".join(lines)
