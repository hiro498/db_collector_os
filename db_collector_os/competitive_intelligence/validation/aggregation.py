"""Site-wide keyword aggregation (spec section 8). Rolls PHASE 1's
per-page `ci_page_keywords` / `ci_keyword_occurrences` / `ci_keyword_modifiers`
rows up to one row per distinct `normalized_keyword` across an entire
crawl_run -- never a simple UNION, and never a re-derivation of the
underlying per-page scores (those stay exactly as PHASE 1 computed them;
this module only sums/averages/unions them across pages).
"""

from __future__ import annotations

from typing import Any

from ...database import Database

_HEADING_TYPES = ("h2", "h3", "h4", "h5", "h6")


def aggregate_site_keywords(db: Database, crawl_run_id: str) -> list[dict[str, Any]]:
    rows = db.query(
        "SELECT pk.page_keyword_id, pk.page_id, pk.keyword_id, pk.score, pk.importance, pk.intent, "
        "       pk.commercial_score, pk.site_structure_score, pk.cross_page_score, "
        "       k.keyword, k.normalized_keyword, k.token_count, p.page_type "
        "FROM ci_page_keywords pk "
        "JOIN ci_keywords k ON k.keyword_id = pk.keyword_id "
        "JOIN ci_pages p ON p.page_id = pk.page_id "
        "WHERE pk.crawl_run_id=?",
        (crawl_run_id,),
    )
    if not rows:
        return []

    occurrence_rows = db.query(
        "SELECT o.page_keyword_id, o.element_type, o.occurrence_count FROM ci_keyword_occurrences o "
        "JOIN ci_page_keywords pk ON pk.page_keyword_id = o.page_keyword_id WHERE pk.crawl_run_id=?",
        (crawl_run_id,),
    )
    occurrences_by_pk: dict[str, list[dict[str, Any]]] = {}
    for o in occurrence_rows:
        occurrences_by_pk.setdefault(o["page_keyword_id"], []).append(o)

    modifier_rows = db.query(
        "SELECT m.page_keyword_id, m.modifier FROM ci_keyword_modifiers m "
        "JOIN ci_page_keywords pk ON pk.page_keyword_id = m.page_keyword_id WHERE pk.crawl_run_id=?",
        (crawl_run_id,),
    )
    modifiers_by_pk: dict[str, set[str]] = {}
    for m in modifier_rows:
        modifiers_by_pk.setdefault(m["page_keyword_id"], set()).add(m["modifier"])

    groups: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = row["normalized_keyword"]
        g = groups.setdefault(key, {
            "keyword": row["keyword"], "normalized_keyword": key, "keyword_id": row["keyword_id"],
            "token_count": row["token_count"],
            "pages": set(), "page_types": set(), "page_type_counts": {}, "scores": [], "intents": [], "commercial_scores": [],
            "site_structure_scores": [], "cross_page_scores": [], "modifiers": set(),
            "title_occurrences": 0, "h1_occurrences": 0, "heading_occurrences": 0,
            "body_occurrences": 0, "anchor_occurrences": 0, "total_occurrences": 0,
        })
        g["pages"].add(row["page_id"])
        g["page_types"].add(row["page_type"])
        g["page_type_counts"][row["page_type"]] = g["page_type_counts"].get(row["page_type"], 0) + 1
        g["scores"].append(row["score"])
        if row["intent"]:
            g["intents"].append(row["intent"])
        g["commercial_scores"].append(row["commercial_score"])
        g["site_structure_scores"].append(row["site_structure_score"])
        g["cross_page_scores"].append(row["cross_page_score"])
        g["modifiers"] |= modifiers_by_pk.get(row["page_keyword_id"], set())
        for occ in occurrences_by_pk.get(row["page_keyword_id"], []):
            count = occ["occurrence_count"]
            g["total_occurrences"] += count
            et = occ["element_type"]
            if et == "title":
                g["title_occurrences"] += count
            elif et == "h1":
                g["h1_occurrences"] += count
            elif et in _HEADING_TYPES:
                g["heading_occurrences"] += count
            elif et == "body":
                g["body_occurrences"] += count
            elif et == "anchor":
                g["anchor_occurrences"] += count

    results = []
    for g in groups.values():
        scores = g["scores"]
        commercial_scores = g["commercial_scores"]
        results.append({
            "keyword": g["keyword"], "normalized_keyword": g["normalized_keyword"], "keyword_id": g["keyword_id"],
            "token_count": g["token_count"],
            "pages_count": len(g["pages"]), "page_types": sorted(g["page_types"]),
            "page_type_counts": dict(g["page_type_counts"]),
            "best_keyword_score": max(scores) if scores else 0,
            "avg_keyword_score": round(sum(scores) / len(scores), 2) if scores else 0.0,
            "total_occurrences": g["total_occurrences"], "title_occurrences": g["title_occurrences"],
            "h1_occurrences": g["h1_occurrences"], "heading_occurrences": g["heading_occurrences"],
            "body_occurrences": g["body_occurrences"], "anchor_occurrences": g["anchor_occurrences"],
            "site_structure_score": round(sum(g["site_structure_scores"]) / len(g["site_structure_scores"]), 2)
                if g["site_structure_scores"] else 0.0,
            "cross_page_score": round(sum(g["cross_page_scores"]) / len(g["cross_page_scores"]), 2)
                if g["cross_page_scores"] else 0.0,
            "intents": g["intents"],
            "avg_commercial_score": round(sum(commercial_scores) / len(commercial_scores), 2)
                if commercial_scores else 0.0,
            "modifiers": g["modifiers"],
        })
    return results
