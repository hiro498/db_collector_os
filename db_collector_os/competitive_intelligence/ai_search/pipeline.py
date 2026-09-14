"""Orchestrates PHASE 12 analysis for one page: reads already-stored
``ci_page_elements`` (never re-fetches HTML -- this is a REANALYZE-style
operation, spec section 18's ``recompute_ai_analysis`` is simply this same
function run again), computes every locally-available signal, and writes
both the aggregate ``ci_ai_page_analysis`` row and the underlying evidence
rows (``ci_ai_numeric_facts``/``ci_ai_comparisons``/``ci_ai_freshness_events``/
``ci_ai_fanout_queries``).
"""

from __future__ import annotations

import json
from typing import Any

from ...database import Database
from . import ai_mode, aio, comparison, fanout, freshness, numeric_facts, proprietary, source_affinity
from .enums import EXTRACTOR_VERSION
from .repository import (
    AiComparisonRepository,
    AiFanoutQueryRepository,
    AiFreshnessEventRepository,
    AiNumericFactRepository,
    AiPageAnalysisRepository,
)
from .tokenizer_utils import proper_noun_count
from .weights import weighted_readiness_score
from ..repository.pages import PageElementRepository, PageRepository

# Elements scanned for AI-search signals (title/H1 excluded on purpose --
# they duplicate content.py's own keyword-position scoring; AI-search
# signals live in the substantive content, not the headline).
_SIGNAL_ELEMENT_TYPES = ("body", "faq", "table", "list", "h2", "h3", "caption")


def analyze_ai_page(db: Database, page_id: str) -> dict[str, Any]:
    page = PageRepository(db).get(page_id)
    if not page:
        raise ValueError(f"no such page: {page_id}")
    elements = [e for e in PageElementRepository(db).list_for_page(page_id) if not e.get("is_boilerplate")]
    body_text = _text_of(elements, "body")

    numeric_candidates, numeric_facts_evidence = _scan_numeric_facts(elements)
    numeric_summary = numeric_facts.summarize(numeric_candidates)
    numeric_quality = numeric_facts.quality_score(numeric_summary)

    prop_hits = _scan_proprietary(elements)
    strong_types = {"derived", "comparison", "ranking", "ratio_percentage"}
    verifiable_fact_count = sum(1 for c in numeric_candidates if c.fact_type in strong_types)
    unique_fact_count = _count_corroborated_facts(numeric_facts_evidence, prop_hits)
    source_trace = proprietary.source_traceability_score(
        len(prop_hits["primary_source_hits"]), len(prop_hits["methodology_hits"])
    )
    prop_score = proprietary.proprietary_information_score(
        len(prop_hits["firsthand_hits"]), len(prop_hits["methodology_hits"]),
        len(prop_hits["proprietary_data_hits"]), len(prop_hits["primary_source_hits"]),
        len(prop_hits["proprietary_metric_hits"]), verifiable_fact_count,
    )

    comparison_candidates, comparison_evidence = _scan_comparisons(elements, body_text)
    comparison_summary = comparison.summarize(comparison_candidates)
    comparison_score = comparison.comparison_information_score(comparison_summary)

    scan_text = " ".join(e["text"] for e in elements if e["text"])
    data_updated_at = freshness.extract_data_updated_at(scan_text)
    change_events, freshness_evidence = _scan_freshness_events(elements)
    timestamp_score = freshness.freshness_timestamp_score(
        page.get("published_at"), page.get("updated_at_source"), data_updated_at
    )
    change_score = freshness.evidence_change_score(change_events)
    fresh_score = freshness.evidence_freshness_score(timestamp_score, change_score)

    aio_signals = aio.compute_aio_signals(body_text)
    ai_mode_signals = ai_mode.compute_ai_mode_signals(
        elements, numeric_summary["numeric_fact_count"], len(comparison_candidates), body_text
    )

    fanout_candidates = _generate_fanout(db, page)
    fanout_score = fanout.fanout_content_coverage_score(fanout_candidates)

    author_signal = source_affinity.detect_author_identity_signal(scan_text)
    editorial_signal = source_affinity.detect_editorial_policy_signal(scan_text)
    site_signals = _site_source_signals(db, page)
    src_score = source_affinity.source_transparency_score(
        author_signal, editorial_signal, site_signals["about_page_signal"],
        site_signals["contact_transparency_signal"], site_signals["source_citation_consistency"],
        site_signals["repeat_entity_coverage"], site_signals["topic_specialization_signal"],
    )

    readiness = weighted_readiness_score({
        "proprietary_information": prop_score,
        "comparison_information": comparison_score,
        "numeric_fact_quality": numeric_quality,
        "evidence_freshness": fresh_score,
        "aio_extractability": aio_signals["aio_extractability_score"],
        "ai_mode_content_coverage": ai_mode_signals["ai_mode_content_coverage_score"],
        "fanout_content_coverage": fanout_score,
        "source_transparency": src_score,
    })

    fields: dict[str, Any] = {
        # section 3: external axes stay NULL -- see module docstring.
        "organic_visibility_score": None, "aio_citation_score": None, "ai_mode_citation_score": None,
        "fanout_coverage_score": None, "source_affinity_score": None, "ai_search_total_score": None,
        "ai_citation_readiness_score": readiness,
        "proprietary_information_score": prop_score, "evidence_freshness_score": fresh_score,

        "primary_source_signal": len(prop_hits["primary_source_hits"]),
        "firsthand_signal": len(prop_hits["firsthand_hits"]),
        "proprietary_data_signal": len(prop_hits["proprietary_data_hits"]),
        "derived_metric_count": len(prop_hits["proprietary_metric_hits"]),
        "unique_fact_count": unique_fact_count,
        "verifiable_fact_count": verifiable_fact_count,
        "sample_size_mentions": numeric_summary["sample_size_count"],
        "methodology_signal": len(prop_hits["methodology_hits"]),
        "source_traceability_score": source_trace,

        **numeric_summary, "numeric_fact_quality_score": numeric_quality,
        **comparison_summary, "comparison_information_score": comparison_score,

        "published_at": page.get("published_at"), "modified_at": page.get("updated_at_source"),
        "data_updated_at": data_updated_at, "freshness_timestamp_score": timestamp_score,
        "evidence_change_score": change_score, "meaningful_update_signal": int(change_score > 0),

        "answer_in_first_100_words": aio_signals["answer_in_first_100_words"],
        "key_fact_in_first_100_words": aio_signals["key_fact_in_first_100_words"],
        "comparison_result_near_top": aio_signals["comparison_result_near_top"],
        "summary_near_top": aio_signals["summary_near_top"],
        "aio_extractability_score": aio_signals["aio_extractability_score"],

        "subtopic_count": ai_mode_signals["subtopic_count"],
        "related_question_count": ai_mode_signals["related_question_count"],
        "entity_coverage_count": ai_mode_signals["entity_coverage_count"],
        "evidence_block_count": ai_mode_signals["evidence_block_count"],
        "ai_mode_content_coverage_score": ai_mode_signals["ai_mode_content_coverage_score"],

        "fanout_content_coverage_score": fanout_score,

        "site_author_identity_signal": int(author_signal), "editorial_policy_signal": int(editorial_signal),
        **site_signals, "source_transparency_score": src_score,
        "external_source_preference_status": None,

        "organic_rank": None, "organic_top10": None, "organic_top20": None, "serp_observed_at": None,
        "aio_cited": None, "aio_citation_position": None, "aio_observed_at": None,
        "ai_mode_cited": None, "ai_mode_citation_position": None, "ai_mode_observed_at": None,
        "citation_first_seen": None, "citation_last_seen": None, "citation_observation_count": None,
        "citation_persistence_score": None,

        "extractor_version": EXTRACTOR_VERSION,
    }

    AiPageAnalysisRepository(db).upsert(page_id, page["crawl_run_id"], **fields)
    AiNumericFactRepository(db).replace_for_page(page_id, numeric_facts_evidence, EXTRACTOR_VERSION)
    AiComparisonRepository(db).replace_for_page(page_id, comparison_evidence, EXTRACTOR_VERSION)
    AiFreshnessEventRepository(db).replace_for_page(page_id, freshness_evidence, EXTRACTOR_VERSION)
    AiFanoutQueryRepository(db).replace_for_page(page_id, [
        {"base_keyword": c.base_keyword, "subquery_text": c.subquery_text,
         "intent_class": c.intent_class, "covered_by_content": c.covered_by_content}
        for c in fanout_candidates
    ])

    return AiPageAnalysisRepository(db).get(page_id)


def recompute_ai_analysis(db: Database, page_id: str) -> dict[str, Any]:
    """Identical to analyze_ai_page: both only ever read stored
    page_elements, so "recompute" and "analyze" are the same operation --
    kept as two names because the CLI/service layer (spec section 18)
    distinguishes first-run from re-run for the operator's benefit."""
    return analyze_ai_page(db, page_id)


def get_ai_analysis(db: Database, page_id: str) -> dict[str, Any] | None:
    return AiPageAnalysisRepository(db).get(page_id)


def _text_of(elements: list[dict], element_type: str) -> str:
    return next((e.get("text") or "" for e in elements if e["element_type"] == element_type), "")


def _attrs_of(element: dict) -> dict:
    """ci_page_elements stores structured attrs as the JSON string
    `attrs_json` (see repository/pages.py); freshly-parsed ParsedPage
    elements instead carry a live `attrs` dict. Accept either so this
    module works the same right after parsing and after a DB round-trip."""
    if "attrs" in element and isinstance(element["attrs"], dict):
        return element["attrs"]
    raw = element.get("attrs_json")
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return {}


def _scan_numeric_facts(elements: list[dict]) -> tuple[list, list[dict]]:
    all_candidates = []
    evidence = []
    for e in elements:
        if e["element_type"] not in _SIGNAL_ELEMENT_TYPES or not e.get("text"):
            continue
        for c in numeric_facts.detect_numeric_facts(e["text"]):
            all_candidates.append(c)
            evidence.append({
                "fact_type": c.fact_type, "signal_value": c.signal_value, "source_text": c.source_text,
                "html_element": e["element_type"], "page_section": e["element_type"], "confidence": c.confidence,
            })
    return all_candidates, evidence


def _scan_proprietary(elements: list[dict]) -> dict[str, list]:
    combined: dict[str, list] = {
        "firsthand_hits": [], "methodology_hits": [], "proprietary_data_hits": [],
        "primary_source_hits": [], "proprietary_metric_hits": [],
    }
    for e in elements:
        if e["element_type"] not in _SIGNAL_ELEMENT_TYPES or not e.get("text"):
            continue
        hits = proprietary.detect_proprietary_signals(e["text"])
        for key in combined:
            combined[key].extend(hits[key])
    return combined


def _count_corroborated_facts(numeric_evidence: list[dict], prop_hits: dict[str, list]) -> int:
    """A numeric fact is "unique" (spec section 4) when it sits alongside
    an explicit firsthand/proprietary/methodology claim, not just any
    number on the page."""
    marker_snippets = [snippet for hits in prop_hits.values() for _pattern, snippet in hits]
    if not marker_snippets:
        return 0
    count = 0
    for fact in numeric_evidence:
        source = fact.get("source_text") or ""
        if any(source in snippet or snippet in source for snippet in marker_snippets):
            count += 1
    return count


def _scan_comparisons(elements: list[dict], body_text: str) -> tuple[list, list[dict]]:
    candidates = []
    evidence = []
    pn_count = proper_noun_count(body_text)
    for e in elements:
        text = e.get("text") or ""
        if not text:
            continue
        candidate = None
        if e["element_type"] == "table":
            candidate = comparison.detect_from_table(text, _attrs_of(e))
        elif e["element_type"] == "list":
            candidate = comparison.detect_from_list(text, _attrs_of(e))
        elif e["element_type"] in ("h2", "h3", "body"):
            structure_type = "heading" if e["element_type"] != "body" else "body"
            candidate = comparison.detect_from_prose(text, structure_type, pn_count)
        if candidate:
            candidates.append(candidate)
            evidence.append({
                "structure_type": candidate.structure_type, "entity_count": candidate.entity_count,
                "dimension_count": candidate.dimension_count, "normalized": candidate.normalized,
                "same_condition": candidate.same_condition, "source_text": candidate.source_text,
                "html_element": e["element_type"], "confidence": candidate.confidence,
            })
    return candidates, evidence


def _scan_freshness_events(elements: list[dict]) -> tuple[list, list[dict]]:
    all_events = []
    evidence = []
    for e in elements:
        if e["element_type"] not in _SIGNAL_ELEMENT_TYPES or not e.get("text"):
            continue
        for ev in freshness.detect_change_events(e["text"]):
            all_events.append(ev)
            evidence.append({
                "event_type": ev.event_type, "before_value": ev.before_value, "after_value": ev.after_value,
                "source_text": ev.source_text, "html_element": e["element_type"], "confidence": ev.confidence,
            })
    return all_events, evidence


def _generate_fanout(db: Database, page: dict) -> list:
    primary = db.query_one(
        "SELECT k.keyword FROM ci_page_keywords pk JOIN ci_keywords k ON k.keyword_id = pk.keyword_id "
        "WHERE pk.page_id=? AND pk.is_primary=1 LIMIT 1",
        (page["page_id"],),
    )
    base_keyword = primary["keyword"] if primary else (page.get("title") or "")
    rows = db.query(
        "SELECT k.branded_type AS branded_type, k.is_local AS is_local, pk.intent AS intent, "
        "m.modifier AS modifier FROM ci_page_keywords pk "
        "JOIN ci_keywords k ON k.keyword_id = pk.keyword_id "
        "LEFT JOIN ci_keyword_modifiers m ON m.page_keyword_id = pk.page_keyword_id "
        "WHERE pk.page_id=?",
        (page["page_id"],),
    )
    modifiers = frozenset(r["modifier"] for r in rows if r["modifier"])
    signals = fanout.PageIntentSignals(
        modifiers=modifiers,
        has_informational=any(r["intent"] == "informational" for r in rows),
        is_branded=any(r["branded_type"] == "branded" for r in rows),
        is_local=any(r["is_local"] for r in rows),
    )
    return fanout.generate_fanout_candidates(base_keyword, signals)


def _site_source_signals(db: Database, page: dict) -> dict[str, int]:
    crawl_run_id = page["crawl_run_id"]
    has_about = db.query_one(
        "SELECT 1 FROM ci_pages WHERE crawl_run_id=? AND page_type='company' LIMIT 1", (crawl_run_id,)
    ) is not None
    has_contact = db.query_one(
        "SELECT 1 FROM ci_pages WHERE crawl_run_id=? AND page_type='contact' LIMIT 1", (crawl_run_id,)
    ) is not None
    citation_row = db.query_one(
        "SELECT COUNT(DISTINCT target_domain) AS n FROM ci_outbound_links "
        "WHERE source_page_id=? AND link_type='other'",
        (page["page_id"],),
    )
    repeat_row = db.query_one(
        "SELECT COUNT(*) AS n FROM ci_page_keywords WHERE page_id=? AND keyword_id IN ("
        " SELECT keyword_id FROM ci_page_keywords WHERE crawl_run_id=? "
        " GROUP BY keyword_id HAVING COUNT(DISTINCT page_id) > 1)",
        (page["page_id"], crawl_run_id),
    )
    repeat_entity = repeat_row["n"] if repeat_row else 0
    return {
        "about_page_signal": int(has_about),
        "contact_transparency_signal": int(has_contact),
        "source_citation_consistency": citation_row["n"] if citation_row else 0,
        "repeat_entity_coverage": repeat_entity,
        "topic_specialization_signal": min(100, repeat_entity * 10),
    }
