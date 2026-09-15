"""CSV export for the Opportunity Score layer (spec section 27). Reuses
the same `utf-8-sig` convention as `exporter.py` so Japanese text opens
correctly in Excel rather than mojibake.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from ...database import Database
from .repository import ComparisonRepository, ContentGapRepository, OpportunityRepository

_OPPORTUNITIES_HEADER = (
    "entity_type", "keyword", "page_url", "overall_score", "score_status", "confidence", "organic_gap",
    "ai_gap", "fanout_gap", "content_gap", "commercial", "top_reason", "top_action",
)
_COMPARISON_HEADER = (
    "left_entity_type", "left_entity_id", "right_entity_type", "right_entity_id", "comparison_dimension",
    "left_value", "right_value", "gap_value", "winner", "confidence",
)
_CONTENT_GAPS_HEADER = (
    "our_page_id", "competitor_page_id", "content_gap_score", "missing_keywords", "missing_subtopics",
    "missing_entities", "missing_questions", "missing_numeric_facts", "missing_comparison_dimensions",
    "missing_primary_information", "missing_freshness_evidence", "missing_internal_link_topics",
)


def _joined(json_text: str) -> str:
    try:
        items = json.loads(json_text)
    except (TypeError, ValueError):
        return ""
    return "; ".join(items)


def export_opportunities(db: Database, out_path: Path, entity_type: str | None = None) -> Path:
    repo = OpportunityRepository(db)
    rows = repo.list_analyses(entity_type=entity_type, limit=10_000)
    with open(out_path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(_OPPORTUNITIES_HEADER)
        for row in rows:
            page = db.query_one("SELECT url FROM ci_pages WHERE page_id=?", (row["our_page_id"],)) if row["our_page_id"] else None
            reasons = repo.reasons_for(row["opportunity_id"])
            actions = repo.actions_for(row["opportunity_id"])
            writer.writerow([
                row["entity_type"], row["query"] or "", page["url"] if page else "",
                row["overall_opportunity_score"], row["score_status"], row["confidence_label"],
                _component_value(repo, row["opportunity_id"], "organic_gap_score"),
                row["ai_opportunity_score"], row["fanout_opportunity_score"], row["content_gap_score"],
                row["commercial_opportunity_score"], reasons[0]["reason_code"] if reasons else "",
                actions[0]["action_code"] if actions else "",
            ])
    return out_path


def _component_value(repo: OpportunityRepository, opportunity_id: str, name: str) -> Any:
    for c in repo.components_for(opportunity_id):
        if c["component_name"] == name:
            return c["value"]
    return None


def export_competitor_comparisons(db: Database, out_path: Path) -> Path:
    rows = db.query("SELECT * FROM ci_competitor_comparisons ORDER BY computed_at DESC LIMIT 10000")
    with open(out_path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(_COMPARISON_HEADER)
        for row in rows:
            writer.writerow([
                row["left_entity_type"], row["left_entity_id"], row["right_entity_type"], row["right_entity_id"],
                row["comparison_dimension"], row["left_value"], row["right_value"], row["gap_value"],
                row["winner"], row["confidence"],
            ])
    return out_path


def export_content_gaps(db: Database, out_path: Path) -> Path:
    rows = db.query("SELECT * FROM ci_content_gaps ORDER BY content_gap_score DESC LIMIT 10000")
    with open(out_path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(_CONTENT_GAPS_HEADER)
        for row in rows:
            writer.writerow([
                row["our_page_id"], row["competitor_page_id"], row["content_gap_score"],
                _joined(row["missing_keywords_json"]), _joined(row["missing_subtopics_json"]),
                _joined(row["missing_entities_json"]), _joined(row["missing_questions_json"]),
                _joined(row["missing_numeric_facts_json"]), _joined(row["missing_comparison_dimensions_json"]),
                _joined(row["missing_primary_information_json"]), _joined(row["missing_freshness_evidence_json"]),
                _joined(row["missing_internal_link_topics_json"]),
            ])
    return out_path


def export_all(db: Database, out_dir: str) -> list[str]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = [
        export_opportunities(db, out / "opportunities.csv"),
        export_competitor_comparisons(db, out / "competitor_comparison.csv"),
        export_content_gaps(db, out / "content_gaps.csv"),
    ]
    return [str(p) for p in paths]
