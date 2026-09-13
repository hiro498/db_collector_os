"""Per-page keyword extraction/scoring (phase 1) and run-level finalize
(phase 2) -- spec sections 19-24, 27, 32.

Split in two because content_score needs corpus-wide document frequency,
not known until every analyzed page in a crawl_run has been through phase
1. REANALYZE (section 45) re-runs phase 1 for changed pages, then always
re-runs phase 2 for the whole run so scores stay consistent.
"""

from __future__ import annotations

from typing import Any

from ...database import Database
from ..enums import PageType
from ..repository.keywords import KeywordClusterRepository, KeywordRepository
from ..repository.pages import PageRepository
from ..repository.site import SiteProfileRepository
from ..vertical.base import VerticalProfile, get_vertical
from . import cluster as cluster_mod
from . import intent as intent_mod
from . import modifiers as modifiers_mod
from . import scorer
from .candidate import generate_candidates
from .normalizer import classify_branded, classify_keyword_class, detect_locality, normalize_keyword
from .tokenizer import get_default_tokenizer

# Elements re-scanned for keyword candidates. body_lead is a display-only
# duplicate of the start of `body` (see parser/html_parser.py) and is
# deliberately excluded here so its keywords aren't double-counted.
_SCANNED_ELEMENT_TYPES = (
    "title", "meta_description", "h1", "h2", "h3", "h4", "h5", "h6", "url_slug",
    "breadcrumb", "category", "tag", "strong", "anchor", "alt", "caption",
    "table", "faq", "cta", "button", "body",
    "sidebar", "related_articles_heading", "popular_articles_heading", "ranking_heading",
)


def extract_page_candidates(elements: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """normalized_keyword -> {raw_keyword, token_count,
    occurrences: {element_type: {count, first_position, evidence_text}}}"""
    tokenizer = get_default_tokenizer()
    aggregated: dict[str, dict[str, Any]] = {}
    for element in elements:
        if element.get("is_boilerplate"):
            continue
        element_type = element["element_type"]
        if element_type not in _SCANNED_ELEMENT_TYPES:
            continue
        text = element.get("text") or ""
        for cand in generate_candidates(text, tokenizer):
            norm = normalize_keyword(cand.text)
            if not norm:
                continue
            entry = aggregated.setdefault(norm, {
                "raw_keyword": cand.text, "token_count": cand.token_count, "occurrences": {},
            })
            occ = entry["occurrences"].setdefault(
                element_type, {"count": 0, "first_position": cand.start_offset, "evidence_text": text[:120]}
            )
            occ["count"] += 1
            occ["first_position"] = min(occ["first_position"], cand.start_offset)
    return aggregated


def score_and_store_page(
    db: Database,
    page_id: str,
    crawl_run_id: str,
    elements: list[dict[str, Any]],
    vertical: VerticalProfile | None = None,
) -> None:
    """Phase 1: page-local scoring for every candidate keyword on one page.
    Overwrites any previous keyword data for this page (fresh parse or
    REANALYZE both call this)."""
    keyword_repo = KeywordRepository(db)
    keyword_repo.delete_page_keywords_for_page(page_id)
    vertical = vertical or get_vertical(None)

    candidates = extract_page_candidates(elements)
    for normalized, data in candidates.items():
        occurrences: dict[str, dict] = data["occurrences"]
        element_types_present = set(occurrences.keys())
        title_hit = "title" in occurrences
        h1_hit = "h1" in occurrences
        h2_count = occurrences.get("h2", {}).get("count", 0)
        h3_count = occurrences.get("h3", {}).get("count", 0)
        body_count = occurrences.get("body", {}).get("count", 0)
        anchor_count = occurrences.get("anchor", {}).get("count", 0)
        url_slug_hit = "url_slug" in occurrences

        modifiers = modifiers_mod.detect_modifiers(normalized, vertical)
        comm_score = modifiers_mod.commercial_score(modifiers)
        locality = detect_locality(normalized, get_default_tokenizer())
        branded_type = classify_branded(normalized, vertical.brand_terms())
        intent, intent_group = intent_mod.classify_intent(
            normalized, modifiers, bool(locality["is_local"]), branded_type
        )
        keyword_class = classify_keyword_class(data["token_count"], len(modifiers))

        keyword_row = keyword_repo.get_or_create(data["raw_keyword"], normalized, data["token_count"])
        keyword_repo.update_classification(
            keyword_row["keyword_id"], branded_type=branded_type, is_local=1 if locality["is_local"] else 0,
            prefecture=locality["prefecture"], city=locality["city"], ward=locality["ward"],
            station=locality["station"], keyword_class=keyword_class,
        )

        html_score = scorer.compute_html_score(element_types_present)
        phrase_score = scorer.compute_phrase_score(data["token_count"])
        intent_score = intent_mod.intent_score_component(intent)
        rule_boost, reasons = scorer.compute_page_level_rule_boost(title_hit, h1_hit, h2_count, url_slug_hit)

        page_keyword_id = keyword_repo.upsert_page_keyword(
            page_id, keyword_row["keyword_id"], crawl_run_id,
            html_score=html_score, content_score=0, phrase_score=phrase_score,
            site_structure_score=0, intent_score=intent_score, cross_page_score=0,
            rule_boost=rule_boost, rule_boost_reasons_json=_json(reasons),
            importance="noise", intent=intent, intent_group=intent_group, commercial_score=comm_score,
            is_primary=0, title_hit=1 if title_hit else 0, h1_hit=1 if h1_hit else 0,
            h2_count=h2_count, h3_count=h3_count, body_count=body_count, anchor_count=anchor_count,
        )
        for element_type, occ in occurrences.items():
            weight = scorer.HTML_POSITION_WEIGHTS.get(element_type, scorer.DEFAULT_ELEMENT_WEIGHT)
            keyword_repo.add_occurrence(
                page_keyword_id, element_type, occ["count"], occ["first_position"], weight, occ["evidence_text"]
            )
        keyword_repo.add_modifiers(page_keyword_id, modifiers)


def finalize_run(db: Database, crawl_run_id: str) -> None:
    """Phase 2: cross-page scoring, clustering, and site aggregation for an
    entire crawl_run. Safe to call repeatedly (KW再計算 / section 45)."""
    keyword_repo = KeywordRepository(db)
    cluster_repo = KeywordClusterRepository(db)
    page_repo = PageRepository(db)

    total_docs = page_repo.analyzed_count_for_run(crawl_run_id)
    page_keywords = db.query(
        "SELECT pk.*, p.page_type FROM ci_page_keywords pk JOIN ci_pages p ON p.page_id = pk.page_id "
        "WHERE pk.crawl_run_id=?",
        (crawl_run_id,),
    )
    by_keyword: dict[str, list[dict]] = {}
    for row in page_keywords:
        by_keyword.setdefault(row["keyword_id"], []).append(row)

    category_tag_pages = db.query(
        "SELECT DISTINCT pk.keyword_id FROM ci_page_keywords pk JOIN ci_pages p ON p.page_id = pk.page_id "
        "WHERE pk.crawl_run_id=? AND p.page_type IN (?, ?)",
        (crawl_run_id, PageType.CATEGORY, PageType.TAG),
    )
    hub_keyword_ids = {r["keyword_id"] for r in category_tag_pages}

    best_per_page: dict[str, tuple[str, int]] = {}  # page_id -> (page_keyword_id, score)

    for keyword_id, rows in by_keyword.items():
        page_count = len({r["page_id"] for r in rows})
        article_page_count = sum(1 for r in rows if r["page_type"] == PageType.ARTICLE)
        doc_freq = page_count
        site_structure_score = scorer.compute_site_structure_score(page_count)
        cross_page_score = scorer.compute_cross_page_score(page_count)

        for row in rows:
            occurrences = keyword_repo.list_occurrences(row["page_keyword_id"])
            body_occ = next((o for o in occurrences if o["element_type"] == "body"), None)
            occurrences_in_body = body_occ["occurrence_count"] if body_occ else 0
            appears_in_lead = bool(body_occ and body_occ["first_position"] is not None and body_occ["first_position"] < 200)
            content_score = scorer.compute_content_score(occurrences_in_body, doc_freq, total_docs, appears_in_lead)

            rule_boost = row["rule_boost"]
            reasons = _from_json(row["rule_boost_reasons_json"])
            if keyword_id in hub_keyword_ids and article_page_count >= 2:
                if row["page_type"] == PageType.CATEGORY and "category_multiple_articles" not in reasons:
                    rule_boost += scorer.RULE_BOOST_CATEGORY_MULTI_ARTICLE
                    reasons.append("category_multiple_articles")
                elif row["page_type"] == PageType.TAG and "tag_multiple_articles" not in reasons:
                    rule_boost += scorer.RULE_BOOST_TAG_MULTI_ARTICLE
                    reasons.append("tag_multiple_articles")

            breakdown = scorer.ScoreBreakdown(
                html_score=row["html_score"], content_score=content_score, phrase_score=row["phrase_score"],
                site_structure_score=site_structure_score, intent_score=row["intent_score"],
                cross_page_score=cross_page_score, rule_boost=rule_boost,
            )
            keyword_repo.upsert_page_keyword(
                row["page_id"], keyword_id, crawl_run_id,
                content_score=content_score, site_structure_score=site_structure_score,
                cross_page_score=cross_page_score, rule_boost=rule_boost,
                rule_boost_reasons_json=_json(reasons), score=breakdown.total, importance=breakdown.importance,
            )
            current_best = best_per_page.get(row["page_id"])
            if current_best is None or breakdown.total > current_best[1]:
                best_per_page[row["page_id"]] = (row["page_keyword_id"], breakdown.total)

    if best_per_page:
        db.execute(
            "UPDATE ci_page_keywords SET is_primary=0 WHERE crawl_run_id=?", (crawl_run_id,)
        )
        for page_keyword_id, _score in best_per_page.values():
            db.execute(
                "UPDATE ci_page_keywords SET is_primary=1 WHERE page_keyword_id=?", (page_keyword_id,)
            )

    _rebuild_clusters(db, crawl_run_id, cluster_repo)
    _update_site_profile(db, crawl_run_id)


def _rebuild_clusters(db: Database, crawl_run_id: str, cluster_repo: KeywordClusterRepository) -> None:
    cluster_repo.clear_for_run(crawl_run_id)
    keywords = db.query(
        "SELECT DISTINCT k.keyword_id, k.keyword FROM ci_keywords k "
        "JOIN ci_page_keywords pk ON pk.keyword_id = k.keyword_id WHERE pk.crawl_run_id=?",
        (crawl_run_id,),
    )
    groups = cluster_mod.build_clusters(keywords, get_default_tokenizer())
    for anchor, keyword_ids in groups.items():
        cluster_id = cluster_repo.create(crawl_run_id, label=anchor)
        for keyword_id in keyword_ids:
            cluster_repo.add_member(cluster_id, keyword_id)


def _update_site_profile(db: Database, crawl_run_id: str) -> None:
    run = db.query_one("SELECT domain_id FROM ci_crawl_runs WHERE crawl_run_id=?", (crawl_run_id,))
    if not run:
        return
    total_pages = db.query_one("SELECT COUNT(*) AS n FROM ci_pages WHERE crawl_run_id=?", (crawl_run_id,))["n"]
    analyzed_pages = db.query_one(
        "SELECT COUNT(*) AS n FROM ci_pages WHERE crawl_run_id=? AND analysis_target=1", (crawl_run_id,)
    )["n"]
    total_keywords = db.query_one(
        "SELECT COUNT(DISTINCT keyword_id) AS n FROM ci_page_keywords WHERE crawl_run_id=?", (crawl_run_id,)
    )["n"]
    commercial_keyword_count = db.query_one(
        "SELECT COUNT(DISTINCT keyword_id) AS n FROM ci_page_keywords WHERE crawl_run_id=? AND commercial_score >= 40",
        (crawl_run_id,),
    )["n"]
    SiteProfileRepository(db).upsert(
        run["domain_id"], crawl_run_id, total_pages=total_pages, analyzed_pages=analyzed_pages,
        total_keywords=total_keywords, commercial_keyword_count=commercial_keyword_count,
    )


def _json(value: list[str]) -> str:
    import json
    return json.dumps(value, ensure_ascii=False)


def _from_json(text: str) -> list[str]:
    import json
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return []
