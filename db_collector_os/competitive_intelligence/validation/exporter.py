"""Output files for a Production Validation run (spec section 22).
`utf-8-sig` throughout so Japanese text never mojibakes in Excel --
the same convention as exporter.py / opportunity/exporter.py.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from ...database import Database
from .repository import DomainKeywordSummaryRepository, TargetKeywordPriorityRepository, ValidationRunRepository

_PAGES_HEADER = ("url", "page_type", "analysis_target", "monetization_type", "monetization_score")
_KEYWORDS_HEADER = (
    "keyword", "normalized_keyword", "pages_count", "best_keyword_score", "avg_keyword_score",
    "primary_intent", "commercial_score", "money_keyword_class", "audit_class_auto", "audit_class",
    "is_noise", "noise_reason",
)
_TARGET_KEYWORDS_HEADER = (
    "rank", "keyword", "normalized_keyword", "intent", "commercial_score", "money_keyword_class",
    "competitor_page_count", "best_competitor_page", "keyword_score", "ai_readiness", "organic_rank",
    "aio_cited", "ai_mode_cited", "content_gap_score", "opportunity_score", "confidence", "top_reason",
    "recommended_action", "demand_status",
)
_CONTENT_MAP_HEADER = (
    "topic", "keyword_count", "page_count", "article_count", "category_count", "ranking_count",
    "comparison_count", "commercial_keyword_count",
)
_OPPORTUNITIES_HEADER = (
    "keyword", "opportunity_score", "content_gap_score", "score_status", "confidence_label",
    "confidence_value", "top_reason_code", "recommended_action",
)
_NOISE_AUDIT_HEADER = ("keyword", "best_keyword_score", "noise_reason")
_ERRORS_HEADER = ("message",)


def _write_csv(path: Path, header: tuple[str, ...], rows: list[tuple[Any, ...]]) -> Path:
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)
    return path


def export_all(db: Database, validation_run_id: str, out_dir: str) -> list[str]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    run = ValidationRunRepository(db).get(validation_run_id)
    if not run:
        raise ValueError(f"unknown validation_run_id: {validation_run_id}")
    summary = json.loads(run["summary_json"]) if run["summary_json"] else {}

    summary_path = out / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    pages = db.query(
        "SELECT url, page_type, analysis_target, monetization_type, monetization_score FROM ci_pages "
        "WHERE crawl_run_id=? ORDER BY page_type, url",
        (run["crawl_run_id"],),
    )
    pages_path = _write_csv(out / "pages.csv", _PAGES_HEADER, [
        (p["url"], p["page_type"], p["analysis_target"], p["monetization_type"], p["monetization_score"])
        for p in pages
    ])

    keywords = DomainKeywordSummaryRepository(db).list_for_run(validation_run_id)
    keywords_all_path = _write_csv(out / "keywords_all.csv", _KEYWORDS_HEADER, [
        (k["keyword"], k["normalized_keyword"], k["pages_count"], k["best_keyword_score"], k["avg_keyword_score"],
         k["primary_intent"], k["commercial_score"], k["money_keyword_class"], k["audit_class_auto"],
         k["audit_class"], k["is_noise"], k["noise_reason"])
        for k in keywords
    ])
    top100 = sorted(
        [k for k in keywords if k["cluster_is_representative"] and not k["is_noise"]],
        key=lambda k: k["best_keyword_score"], reverse=True,
    )[:100]
    keywords_top100_path = _write_csv(out / "keywords_top100.csv", _KEYWORDS_HEADER, [
        (k["keyword"], k["normalized_keyword"], k["pages_count"], k["best_keyword_score"], k["avg_keyword_score"],
         k["primary_intent"], k["commercial_score"], k["money_keyword_class"], k["audit_class_auto"],
         k["audit_class"], k["is_noise"], k["noise_reason"])
        for k in top100
    ])

    noise_rows = [k for k in keywords if k["is_noise"]]
    noise_audit_path = _write_csv(out / "noise_audit.csv", _NOISE_AUDIT_HEADER, [
        (k["keyword"], k["best_keyword_score"], k["noise_reason"]) for k in noise_rows
    ])

    priorities = TargetKeywordPriorityRepository(db).list_for_run(validation_run_id)
    target_keywords_path = _write_csv(out / "target_keywords.csv", _TARGET_KEYWORDS_HEADER, [
        (p["priority_rank"], p["keyword"], p["normalized_keyword"], p["intent"], p["commercial_score"],
         p["money_keyword_class"], p["competitor_page_count"], p["best_competitor_page_url"],
         p["best_competitor_score"], p["ai_readiness"], p["organic_rank"], p["aio_cited"], p["ai_mode_cited"],
         p["content_gap_score"], p["opportunity_score"],
         f"{p['confidence_label']} ({p['confidence_value']})" if p["confidence_label"] else None,
         p["top_reason_text"], p["recommended_action"], p["demand_status"])
        for p in priorities
    ])

    opportunities_path = _write_csv(out / "opportunities.csv", _OPPORTUNITIES_HEADER, [
        (p["keyword"], p["opportunity_score"], p["content_gap_score"], p["score_status"], p["confidence_label"],
         p["confidence_value"], p["top_reason_code"], p["recommended_action"])
        for p in priorities
    ])

    content_map_path = _write_csv(out / "content_map.csv", _CONTENT_MAP_HEADER, [
        (t["topic"], t["keyword_count"], t["page_count"], t["article_count"], t["category_count"],
         t["ranking_count"], t["comparison_count"], t["commercial_keyword_count"])
        for t in summary.get("content_map", [])
    ])

    errors_path = _write_csv(
        out / "errors.csv", _ERRORS_HEADER,
        [(e,) for e in summary.get("errors", [])] + [(f"WARNING: {w}",) for w in summary.get("warnings", [])],
    )

    return [str(p) for p in (
        summary_path, pages_path, keywords_all_path, keywords_top100_path, target_keywords_path,
        content_map_path, opportunities_path, noise_audit_path, errors_path,
    )]
