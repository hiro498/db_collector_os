"""Orchestration for the PHASE 14 Opportunity Score layer. Ties together
PHASE 1 (keywords, monetization, internal links), PHASE 12 (AI Search
Analysis evidence), and PHASE 13 (external observation/readiness-vs-
reality) into per-page and per-keyword Opportunity analyses, pairwise
comparisons, content gaps, reasons, and recommended actions.

"Our page" is always an explicit page_id -- this module never silently
guesses which domain/page is "ours" among several candidates. Competitor
pages default to "other pages (different domain) sharing at least one
target keyword," but callers can always pass an explicit list instead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ...database import Database
from ..ai_search.observation.classification import any_cited
from ..keyword.tokenizer import get_default_tokenizer
from ..link_analyzer import compute_link_metrics
from .actions import generate_actions
from .comparison import DIMENSIONS, compare_dimension
from .competitor_strength import CompetitorStrengthInputs, compute_competitor_strength, internal_link_strength_score
from .components import (
    ComponentResult,
    ai_gap_score,
    commercial_score,
    competition_score,
    content_gap_component,
    demand_score,
    fanout_gap_score,
    freshness_gap_score,
    monetization_score,
    organic_gap_score,
    proprietary_gap_score,
    source_strength_gap_score,
)
from .config import DEFAULT_WEIGHTS, OpportunityWeights
from .content_gap import ContentGapResult, compute_content_gap
from .divergence import classify_organic_ai_divergence
from .enums import ConfidenceLabel
from .reasons import ReasonInputs, generate_reasons
from .repository import ComparisonRepository, ContentGapRepository, KeywordMetricsRepository, OpportunityRepository
from .scoring import aggregate

_QUESTION_RE = re.compile(r"[?？]")

_PAGE_LEVEL_COMPONENTS = (
    "organic_gap_score", "ai_gap_score", "fanout_gap_score", "content_gap_score",
    "proprietary_gap_score", "freshness_gap_score", "source_strength_gap_score",
)
_COMMERCIAL_COMPONENTS = ("commercial_score", "monetization_score")


@dataclass
class PageContext:
    page: dict[str, Any]
    domain_id: str
    crawl_run_id: str
    ai_analysis: dict[str, Any] | None
    visibility: dict[str, Any] | None
    keywords: list[dict[str, Any]]
    subtopics: set[str]
    questions: set[str]
    entities: set[str]
    numeric_facts: list[str]
    comparison_structures: set[str]
    primary_signals: set[str]
    freshness_events: list[str]
    internal_link_topics: set[str]


def _extract_subtopics(elements: list[dict[str, Any]]) -> set[str]:
    return {
        (e["text"] or "").strip() for e in elements
        if not e.get("is_boilerplate") and e["element_type"] in ("h2", "h3") and (e["text"] or "").strip()
    }


def _extract_questions(elements: list[dict[str, Any]]) -> set[str]:
    result: set[str] = set()
    for e in elements:
        if e.get("is_boilerplate"):
            continue
        text = (e["text"] or "").strip()
        if not text:
            continue
        if e["element_type"] == "faq" or (e["element_type"] in ("h1", "h2", "h3", "h4") and _QUESTION_RE.search(text)):
            result.add(text)
    return result


def _extract_entities(elements: list[dict[str, Any]]) -> set[str]:
    body_text = " ".join((e["text"] or "") for e in elements if not e.get("is_boilerplate"))
    if not body_text.strip():
        return set()
    tokenizer = get_default_tokenizer()
    return {m.surface for m in tokenizer.tokenize(body_text) if m.is_proper_noun}


def _build_page_context(db: Database, page_id: str) -> PageContext | None:
    page = db.query_one("SELECT * FROM ci_pages WHERE page_id=?", (page_id,))
    if not page:
        return None
    ai_analysis = db.query_one("SELECT * FROM ci_ai_page_analysis WHERE page_id=?", (page_id,))
    visibility = db.query_one("SELECT * FROM ci_ai_page_visibility WHERE page_id=?", (page_id,))
    elements = db.query("SELECT * FROM ci_page_elements WHERE page_id=?", (page_id,))
    keywords = db.query(
        "SELECT pk.*, k.keyword AS keyword_text, k.normalized_keyword FROM ci_page_keywords pk "
        "JOIN ci_keywords k ON k.keyword_id = pk.keyword_id WHERE pk.page_id=?", (page_id,),
    )
    numeric_facts = [
        r["source_text"] for r in db.query(
            "SELECT source_text FROM ci_ai_numeric_facts WHERE page_id=? AND source_text IS NOT NULL", (page_id,)
        )
    ]
    comparison_structures = {
        r["structure_type"] for r in db.query(
            "SELECT DISTINCT structure_type FROM ci_ai_comparisons WHERE page_id=?", (page_id,)
        )
    }
    primary_signals = set()
    if ai_analysis:
        for flag in ("primary_source_signal", "firsthand_signal", "proprietary_data_signal", "methodology_signal"):
            if ai_analysis.get(flag):
                primary_signals.add(flag)
    freshness_events = [
        r["event_type"] for r in db.query("SELECT event_type FROM ci_ai_freshness_events WHERE page_id=?", (page_id,))
    ]
    internal_link_topics = {
        r["anchor_text"].strip() for r in db.query(
            "SELECT anchor_text FROM ci_internal_links WHERE source_page_id=? AND anchor_text IS NOT NULL",
            (page_id,),
        ) if r["anchor_text"] and r["anchor_text"].strip()
    }
    return PageContext(
        page=page, domain_id=page["domain_id"], crawl_run_id=page["crawl_run_id"], ai_analysis=ai_analysis,
        visibility=visibility, keywords=keywords, subtopics=_extract_subtopics(elements),
        questions=_extract_questions(elements), entities=_extract_entities(elements), numeric_facts=numeric_facts,
        comparison_structures=comparison_structures, primary_signals=primary_signals,
        freshness_events=freshness_events, internal_link_topics=internal_link_topics,
    )


def _bool_or_none(value: Any) -> bool | None:
    return None if value is None else bool(value)


def _num_or_none(value: Any) -> float | None:
    return None if value is None else float(value)


def _pct_or_none(value: Any) -> float | None:
    return None if value is None else float(value) * 100


def _avg_commercial(ctx: PageContext) -> float | None:
    scored = [k["commercial_score"] for k in ctx.keywords if k["importance"] != "noise"]
    return sum(scored) / len(scored) if scored else None


def _link_metrics_for(db: Database, crawl_run_id: str, cache: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if crawl_run_id not in cache:
        cache[crawl_run_id] = compute_link_metrics(db, crawl_run_id)
    return cache[crawl_run_id]


def _auto_competitors_for_page(db: Database, page_id: str, domain_id: str) -> list[str]:
    rows = db.query(
        "SELECT DISTINCT pk2.page_id FROM ci_page_keywords pk1 "
        "JOIN ci_page_keywords pk2 ON pk2.keyword_id = pk1.keyword_id AND pk2.page_id != pk1.page_id "
        "JOIN ci_pages p2 ON p2.page_id = pk2.page_id "
        "WHERE pk1.page_id=? AND p2.domain_id != ?",
        (page_id, domain_id),
    )
    return [r["page_id"] for r in rows]


def _auto_competitors_for_keyword(db: Database, keyword_id: str, our_page_id: str) -> list[str]:
    rows = db.query(
        "SELECT DISTINCT page_id FROM ci_page_keywords WHERE keyword_id=? AND page_id != ?",
        (keyword_id, our_page_id),
    )
    return [r["page_id"] for r in rows]


def _compute_opportunity_core(
    db: Database, entity_type: str, entity_id: str, our_page_id: str, competitor_page_ids: list[str],
    weights: OpportunityWeights, extra_fields: dict[str, Any],
) -> dict[str, Any]:
    our = _build_page_context(db, our_page_id)
    if our is None:
        raise ValueError(f"unknown page_id: {our_page_id}")

    link_cache: dict[str, dict[str, Any]] = {}
    competitor_contexts = [c for pid in competitor_page_ids if (c := _build_page_context(db, pid)) is not None]

    strengths = []
    for c in competitor_contexts:
        lm = _link_metrics_for(db, c.crawl_run_id, link_cache).get(c.page["page_id"], {})
        v = c.visibility
        strength_inputs = CompetitorStrengthInputs(
            organic_rank=v["organic_rank"] if v else None,
            ai_cited=any_cited(_bool_or_none(v["aio_cited"]), _bool_or_none(v["ai_mode_cited"])) if v else None,
            subtopic_count=c.ai_analysis["subtopic_count"] if c.ai_analysis else 0,
            related_question_count=c.ai_analysis["related_question_count"] if c.ai_analysis else 0,
            entity_coverage_count=c.ai_analysis["entity_coverage_count"] if c.ai_analysis else 0,
            proprietary_information_score=c.ai_analysis["proprietary_information_score"] if c.ai_analysis else None,
            evidence_freshness_score=c.ai_analysis["evidence_freshness_score"] if c.ai_analysis else None,
            inbound_link_count=lm.get("inbound_count", 0), pagerank=lm.get("pagerank", 0.0),
            monetization_score=c.page.get("monetization_score"),
        )
        strengths.append((c, compute_competitor_strength(strength_inputs)))

    observed_ranks = [v["organic_rank"] for c, _ in strengths if (v := c.visibility) and v["organic_rank"] is not None]
    best_organic_rank = min(observed_ranks) if observed_ranks else None
    best_organic_ctx = next(
        (c for c, _ in strengths if c.visibility and c.visibility["organic_rank"] == best_organic_rank), None,
    ) if best_organic_rank is not None else None

    strongest = max(strengths, key=lambda cs: (cs[1].competitor_strength_score or -1.0), default=None)
    strongest_ctx = strongest[0] if strongest else None

    # ---- content gap (persist one row per competitor; use the strongest for the rolled-up component score) ----
    content_gap_repo = ContentGapRepository(db)
    our_keyword_set = {k["normalized_keyword"] for k in our.keywords if k["importance"] != "noise"}
    content_gap_by_competitor: dict[str, ContentGapResult] = {}
    for c in competitor_contexts:
        competitor_keyword_set = {k["normalized_keyword"] for k in c.keywords if k["importance"] != "noise"}
        result = compute_content_gap(
            our_keywords=our_keyword_set, competitor_keywords=competitor_keyword_set,
            our_subtopics=our.subtopics, competitor_subtopics=c.subtopics,
            our_entities=our.entities, competitor_entities=c.entities,
            our_questions=our.questions, competitor_questions=c.questions,
            our_numeric_facts=our.numeric_facts, competitor_numeric_facts=c.numeric_facts,
            our_comparison_structures=our.comparison_structures, competitor_comparison_structures=c.comparison_structures,
            our_primary_signals=our.primary_signals, competitor_primary_signals=c.primary_signals,
            our_freshness_events=our.freshness_events, competitor_freshness_events=c.freshness_events,
            our_internal_link_topics=our.internal_link_topics, competitor_internal_link_topics=c.internal_link_topics,
        )
        content_gap_by_competitor[c.page["page_id"]] = result
        content_gap_repo.upsert(our_page_id, c.page["page_id"], result)

    strongest_content_gap = content_gap_by_competitor.get(strongest_ctx.page["page_id"]) if strongest_ctx else None

    # ---- components ----
    query = _primary_query_for(our)
    metrics_row = KeywordMetricsRepository(db).latest_for_query(query) if query else None
    competitor_strength_values = [s.competitor_strength_score for _, s in strengths if s.competitor_strength_score is not None]

    our_ai_cited = any_cited(
        _bool_or_none(our.visibility["aio_cited"]) if our.visibility else None,
        _bool_or_none(our.visibility["ai_mode_cited"]) if our.visibility else None,
    )
    our_organic_rank = our.visibility["organic_rank"] if our.visibility else None

    strongest_ai = strongest_ctx.ai_analysis if strongest_ctx else None
    components: dict[str, ComponentResult] = {
        "demand_score": demand_score(metrics_row),
        "competition_score": competition_score(len(competitor_contexts), competitor_strength_values),
        "organic_gap_score": organic_gap_score(our_organic_rank, best_organic_rank),
        "ai_gap_score": ai_gap_score(our.visibility["readiness_vs_reality_class"] if our.visibility else None),
        "fanout_gap_score": fanout_gap_score(
            our.visibility["fanout_queries_observed"] if our.visibility else 0,
            our.visibility["fanout_visibility_rate"] if our.visibility else None,
        ),
        "content_gap_score": content_gap_component(
            strongest_content_gap.content_gap_score if strongest_content_gap else None
        ),
        "proprietary_gap_score": proprietary_gap_score(
            our.ai_analysis["proprietary_information_score"] if our.ai_analysis else None,
            strongest_ai["proprietary_information_score"] if strongest_ai else None,
        ),
        "freshness_gap_score": freshness_gap_score(
            our.ai_analysis["evidence_freshness_score"] if our.ai_analysis else None,
            strongest_ai["evidence_freshness_score"] if strongest_ai else None,
        ),
        "commercial_score": commercial_score(_avg_commercial(our), len(
            [k for k in our.keywords if k["importance"] != "noise"]
        )),
        "monetization_score": monetization_score(our.page.get("monetization_score")),
        "source_strength_gap_score": source_strength_gap_score(
            our.ai_analysis["source_transparency_score"] if our.ai_analysis else None,
            strongest_ai["source_transparency_score"] if strongest_ai else None,
        ),
    }

    overall = aggregate(components, weights)
    page_agg = aggregate({k: components[k] for k in _PAGE_LEVEL_COMPONENTS}, weights)
    commercial_agg = aggregate({k: components[k] for k in _COMMERCIAL_COMPONENTS}, weights)

    div_score, div_class = classify_organic_ai_divergence(our_organic_rank, our_ai_cited)

    aio_competitors_cited = sum(
        1 for c, _ in strengths if c.visibility and c.visibility["aio_cited"]
    ) if any(c.visibility for c, _ in strengths) else None
    ai_mode_competitors_cited = sum(
        1 for c, _ in strengths if c.visibility and c.visibility["ai_mode_cited"]
    ) if any(c.visibility for c, _ in strengths) else None

    rank_gap = (
        our_organic_rank - best_organic_rank if our_organic_rank is not None and best_organic_rank is not None else None
    )

    fields = dict(
        crawl_run_id=our.crawl_run_id,
        keyword_opportunity_score=overall.value if entity_type == "keyword" else None,
        page_opportunity_score=page_agg.value,
        ai_opportunity_score=components["ai_gap_score"].value,
        fanout_opportunity_score=components["fanout_gap_score"].value,
        commercial_opportunity_score=commercial_agg.value,
        content_gap_score=components["content_gap_score"].value,
        overall_opportunity_score=overall.value,
        score_status=overall.score_status,
        confidence_label=overall.confidence_label,
        confidence_value=overall.confidence_value,
        organic_ai_divergence_score=div_score,
        organic_ai_divergence_class=div_class,
        competitor_count=len(competitor_contexts),
        best_competitor_rank=best_organic_rank,
        best_competitor_page_id=strongest_ctx.page["page_id"] if strongest_ctx else None,
        our_rank=our_organic_rank,
        rank_gap=rank_gap,
        aio_competitors_cited=aio_competitors_cited,
        ai_mode_competitors_cited=ai_mode_competitors_cited,
        our_aio_cited=our.visibility["aio_cited"] if our.visibility else None,
        our_ai_mode_cited=our.visibility["ai_mode_cited"] if our.visibility else None,
        query=None, intent=None,
    )
    fields.update(extra_fields)

    opp_repo = OpportunityRepository(db)
    opportunity_id = opp_repo.upsert_analysis(entity_type, entity_id, our_page_id, **fields)

    opp_repo.replace_components(opportunity_id, [
        {"component_name": name, "value": c.value, "weight": weights.component_weight(name),
         "availability": c.availability, "evidence": c.evidence}
        for name, c in components.items()
    ])

    reason_inputs = ReasonInputs(
        readiness_vs_reality_class=our.visibility["readiness_vs_reality_class"] if our.visibility else None,
        our_organic_rank=our_organic_rank, ai_cited=our_ai_cited,
        our_proprietary=our.ai_analysis["proprietary_information_score"] if our.ai_analysis else None,
        competitor_proprietary=strongest_ai["proprietary_information_score"] if strongest_ai else None,
        our_freshness=our.ai_analysis["evidence_freshness_score"] if our.ai_analysis else None,
        competitor_freshness=strongest_ai["evidence_freshness_score"] if strongest_ai else None,
        our_comparison=our.ai_analysis["comparison_information_score"] if our.ai_analysis else None,
        competitor_comparison=strongest_ai["comparison_information_score"] if strongest_ai else None,
        our_numeric_facts=our.ai_analysis["numeric_fact_quality_score"] if our.ai_analysis else None,
        competitor_numeric_facts=strongest_ai["numeric_fact_quality_score"] if strongest_ai else None,
        fanout_gap_value=components["fanout_gap_score"].value, content_gap_value=components["content_gap_score"].value,
        commercial_value=components["commercial_score"].value, monetization_value=components["monetization_score"].value,
        divergence_class=div_class, organic_gap_value=components["organic_gap_score"].value,
    )
    reasons = generate_reasons(reason_inputs)
    opp_repo.replace_reasons(opportunity_id, [
        {"reason_code": r.reason_code, "reason_text": r.reason_text, "impact_score": r.impact_score,
         "evidence_reference": r.evidence_reference}
        for r in reasons
    ])

    actions = generate_actions(
        reasons, strongest_content_gap, page_exists=True,
        target_page=our_page_id, target_keyword=entity_id if entity_type == "keyword" else None,
    )
    opp_repo.replace_actions(opportunity_id, [
        {"action_code": a.action_code, "priority": a.priority, "reason_code": a.reason_code,
         "target_page": a.target_page, "target_keyword": a.target_keyword}
        for a in actions
    ])

    for c in competitor_contexts:
        compare_pages(db, our_page_id, c.page["page_id"])

    return opp_repo.get_by_id(opportunity_id)


def _primary_query_for(ctx: PageContext) -> str | None:
    if not ctx.keywords:
        return None
    primary = [k for k in ctx.keywords if k["is_primary"]]
    pool = primary or ctx.keywords
    return max(pool, key=lambda k: k["score"])["keyword_text"]


def compute_page_opportunity(
    db: Database, page_id: str, competitor_page_ids: list[str] | None = None,
    weights: OpportunityWeights = DEFAULT_WEIGHTS,
) -> dict[str, Any]:
    page = db.query_one("SELECT domain_id FROM ci_pages WHERE page_id=?", (page_id,))
    if not page:
        raise ValueError(f"unknown page_id: {page_id}")
    if competitor_page_ids is None:
        competitor_page_ids = _auto_competitors_for_page(db, page_id, page["domain_id"])
    return _compute_opportunity_core(db, "page", page_id, page_id, competitor_page_ids, weights, {})


def compute_keyword_opportunity(
    db: Database, keyword_id: str, our_page_id: str, competitor_page_ids: list[str] | None = None,
    weights: OpportunityWeights = DEFAULT_WEIGHTS,
) -> dict[str, Any]:
    keyword_row = db.query_one("SELECT * FROM ci_keywords WHERE keyword_id=?", (keyword_id,))
    if not keyword_row:
        raise ValueError(f"unknown keyword_id: {keyword_id}")
    if competitor_page_ids is None:
        competitor_page_ids = _auto_competitors_for_keyword(db, keyword_id, our_page_id)
    our_pk = db.query_one(
        "SELECT intent FROM ci_page_keywords WHERE page_id=? AND keyword_id=?", (our_page_id, keyword_id)
    )
    return _compute_opportunity_core(
        db, "keyword", keyword_id, our_page_id, competitor_page_ids, weights,
        {"query": keyword_row["keyword"], "intent": our_pk["intent"] if our_pk else None},
    )


def get_opportunity(db: Database, entity_type: str, entity_id: str, our_page_id: str | None = None) -> dict[str, Any] | None:
    """For entity_type='page', `our_page_id` is structurally always equal
    to `entity_id` (a page's opportunity is always evaluated from its own
    perspective) -- defaulted here rather than requiring every caller to
    repeat the same page_id twice."""
    if our_page_id is None and entity_type == "page":
        our_page_id = entity_id
    return OpportunityRepository(db).get_analysis(entity_type, entity_id, our_page_id)


def get_opportunity_detail(db: Database, opportunity_id: str) -> dict[str, Any] | None:
    repo = OpportunityRepository(db)
    analysis = repo.get_by_id(opportunity_id)
    if not analysis:
        return None
    return {
        "analysis": analysis,
        "components": repo.components_for(opportunity_id),
        "reasons": repo.reasons_for(opportunity_id),
        "actions": repo.actions_for(opportunity_id),
    }


def compare_pages(db: Database, page_id_a: str, page_id_b: str) -> list[dict[str, Any]]:
    ctx_a = _build_page_context(db, page_id_a)
    ctx_b = _build_page_context(db, page_id_b)
    if ctx_a is None or ctx_b is None:
        raise ValueError("both page ids must exist")

    link_cache: dict[str, dict[str, Any]] = {}
    lm_a = _link_metrics_for(db, ctx_a.crawl_run_id, link_cache).get(page_id_a, {})
    lm_b = _link_metrics_for(db, ctx_b.crawl_run_id, link_cache).get(page_id_b, {})

    def v(ctx: PageContext, key: str) -> Any:
        return ctx.visibility.get(key) if ctx.visibility else None

    def ai(ctx: PageContext, key: str) -> Any:
        return ctx.ai_analysis.get(key) if ctx.ai_analysis else None

    dims: dict[str, tuple[float | None, float | None, str]] = {
        "organic_rank": (_num_or_none(v(ctx_a, "organic_rank")), _num_or_none(v(ctx_b, "organic_rank")), ConfidenceLabel.HIGH),
        "aio_citation": (_num_or_none(v(ctx_a, "aio_cited")), _num_or_none(v(ctx_b, "aio_cited")), ConfidenceLabel.HIGH),
        "ai_mode_citation": (_num_or_none(v(ctx_a, "ai_mode_cited")), _num_or_none(v(ctx_b, "ai_mode_cited")), ConfidenceLabel.HIGH),
        "fanout_visibility": (
            _pct_or_none(v(ctx_a, "fanout_visibility_rate")), _pct_or_none(v(ctx_b, "fanout_visibility_rate")),
            ConfidenceLabel.MEDIUM,
        ),
        "readiness": (_num_or_none(ai(ctx_a, "ai_citation_readiness_score")), _num_or_none(ai(ctx_b, "ai_citation_readiness_score")), ConfidenceLabel.MEDIUM),
        "proprietary_information": (_num_or_none(ai(ctx_a, "proprietary_information_score")), _num_or_none(ai(ctx_b, "proprietary_information_score")), ConfidenceLabel.MEDIUM),
        "numeric_facts": (_num_or_none(ai(ctx_a, "numeric_fact_quality_score")), _num_or_none(ai(ctx_b, "numeric_fact_quality_score")), ConfidenceLabel.MEDIUM),
        "comparison_quality": (_num_or_none(ai(ctx_a, "comparison_information_score")), _num_or_none(ai(ctx_b, "comparison_information_score")), ConfidenceLabel.MEDIUM),
        "freshness": (_num_or_none(ai(ctx_a, "evidence_freshness_score")), _num_or_none(ai(ctx_b, "evidence_freshness_score")), ConfidenceLabel.MEDIUM),
        "commercial_intent": (_avg_commercial(ctx_a), _avg_commercial(ctx_b), ConfidenceLabel.MEDIUM),
        "monetization": (_num_or_none(ctx_a.page.get("monetization_score")), _num_or_none(ctx_b.page.get("monetization_score")), ConfidenceLabel.MEDIUM),
        "internal_link_strength": (
            internal_link_strength_score(lm_a.get("inbound_count", 0), lm_a.get("pagerank", 0.0)),
            internal_link_strength_score(lm_b.get("inbound_count", 0), lm_b.get("pagerank", 0.0)),
            ConfidenceLabel.MEDIUM,
        ),
    }
    repo = ComparisonRepository(db)
    results = []
    for dimension in DIMENSIONS:
        left, right, confidence = dims[dimension]
        cmp = compare_dimension(dimension, left, right, confidence)
        comparison_id = repo.upsert(
            "page", page_id_a, "page", page_id_b, dimension, cmp.left_value, cmp.right_value, cmp.gap_value,
            cmp.winner, cmp.confidence, f"left={cmp.left_value}, right={cmp.right_value}",
        )
        results.append({
            "comparison_id": comparison_id, "comparison_dimension": dimension, "left_value": cmp.left_value,
            "right_value": cmp.right_value, "gap_value": cmp.gap_value, "winner": cmp.winner, "confidence": cmp.confidence,
        })
    return results


def _domain_page_ids(db: Database, domain_id: str) -> list[str]:
    return [r["page_id"] for r in db.query(
        "SELECT page_id FROM ci_pages WHERE domain_id=? AND analysis_target=1", (domain_id,)
    )]


def _avg(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def compare_domains(db: Database, domain_id_a: str, domain_id_b: str) -> list[dict[str, Any]]:
    pages_a = [_build_page_context(db, pid) for pid in _domain_page_ids(db, domain_id_a)]
    pages_b = [_build_page_context(db, pid) for pid in _domain_page_ids(db, domain_id_b)]
    pages_a = [p for p in pages_a if p is not None]
    pages_b = [p for p in pages_b if p is not None]

    def collect(pages: list[PageContext], getter) -> list[float]:
        return [v for p in pages if (v := getter(p)) is not None]

    dims: dict[str, tuple[float | None, float | None, str]] = {
        "organic_rank": (
            _avg(collect(pages_a, lambda p: p.visibility["organic_rank"] if p.visibility else None)),
            _avg(collect(pages_b, lambda p: p.visibility["organic_rank"] if p.visibility else None)),
            ConfidenceLabel.MEDIUM,
        ),
        "readiness": (
            _avg(collect(pages_a, lambda p: p.ai_analysis["ai_citation_readiness_score"] if p.ai_analysis else None)),
            _avg(collect(pages_b, lambda p: p.ai_analysis["ai_citation_readiness_score"] if p.ai_analysis else None)),
            ConfidenceLabel.MEDIUM,
        ),
        "proprietary_information": (
            _avg(collect(pages_a, lambda p: p.ai_analysis["proprietary_information_score"] if p.ai_analysis else None)),
            _avg(collect(pages_b, lambda p: p.ai_analysis["proprietary_information_score"] if p.ai_analysis else None)),
            ConfidenceLabel.MEDIUM,
        ),
        "freshness": (
            _avg(collect(pages_a, lambda p: p.ai_analysis["evidence_freshness_score"] if p.ai_analysis else None)),
            _avg(collect(pages_b, lambda p: p.ai_analysis["evidence_freshness_score"] if p.ai_analysis else None)),
            ConfidenceLabel.MEDIUM,
        ),
        "commercial_intent": (
            _avg(collect(pages_a, _avg_commercial)), _avg(collect(pages_b, _avg_commercial)), ConfidenceLabel.MEDIUM,
        ),
        "monetization": (
            _avg(collect(pages_a, lambda p: p.page.get("monetization_score"))),
            _avg(collect(pages_b, lambda p: p.page.get("monetization_score"))), ConfidenceLabel.MEDIUM,
        ),
    }
    repo = ComparisonRepository(db)
    results = []
    for dimension, (left, right, confidence) in dims.items():
        cmp = compare_dimension(dimension, left, right, confidence)
        comparison_id = repo.upsert(
            "domain", domain_id_a, "domain", domain_id_b, dimension, cmp.left_value, cmp.right_value,
            cmp.gap_value, cmp.winner, cmp.confidence,
            f"avg over {len(pages_a)} vs {len(pages_b)} analyzed page(s)",
        )
        results.append({"comparison_id": comparison_id, "comparison_dimension": dimension, "winner": cmp.winner})
    return results


def compare_keywords(db: Database, keyword_id_a: str, keyword_id_b: str) -> list[dict[str, Any]]:
    def keyword_stats(keyword_id: str) -> dict[str, Any]:
        keyword_row = db.query_one("SELECT keyword FROM ci_keywords WHERE keyword_id=?", (keyword_id,))
        pk_rows = db.query(
            "SELECT pk.page_id, pk.commercial_score FROM ci_page_keywords pk WHERE pk.keyword_id=?", (keyword_id,)
        )
        ranks = []
        for row in pk_rows:
            v = db.query_one("SELECT organic_rank FROM ci_ai_page_visibility WHERE page_id=?", (row["page_id"],))
            if v and v["organic_rank"] is not None:
                ranks.append(v["organic_rank"])
        metrics = KeywordMetricsRepository(db).latest_for_query(keyword_row["keyword"]) if keyword_row else None
        return {
            "competitor_count": len(pk_rows),
            "best_rank": min(ranks) if ranks else None,
            "avg_commercial": _avg([r["commercial_score"] for r in pk_rows]) if pk_rows else None,
            "demand": metrics["search_volume"] if metrics else None,
        }

    a, b = keyword_stats(keyword_id_a), keyword_stats(keyword_id_b)
    dims = {
        "organic_rank": (a["best_rank"], b["best_rank"], ConfidenceLabel.MEDIUM),
        "commercial_intent": (a["avg_commercial"], b["avg_commercial"], ConfidenceLabel.MEDIUM),
    }
    repo = ComparisonRepository(db)
    results = []
    for dimension, (left, right, confidence) in dims.items():
        cmp = compare_dimension(dimension, _num_or_none(left), _num_or_none(right), confidence)
        comparison_id = repo.upsert(
            "keyword", keyword_id_a, "keyword", keyword_id_b, dimension, cmp.left_value, cmp.right_value,
            cmp.gap_value, cmp.winner, cmp.confidence, f"left={cmp.left_value}, right={cmp.right_value}",
        )
        results.append({"comparison_id": comparison_id, "comparison_dimension": dimension, "winner": cmp.winner})
    # demand and competitor_count are informational (no natural single-value comparison direction beyond size)
    for dimension, (left, right) in {"demand": (a["demand"], b["demand"]),
                                       "competitor_count": (a["competitor_count"], b["competitor_count"])}.items():
        cmp = compare_dimension(dimension, _num_or_none(left), _num_or_none(right), ConfidenceLabel.LOW)
        comparison_id = repo.upsert(
            "keyword", keyword_id_a, "keyword", keyword_id_b, dimension, cmp.left_value, cmp.right_value,
            cmp.gap_value, cmp.winner, cmp.confidence, f"left={cmp.left_value}, right={cmp.right_value}",
        )
        results.append({"comparison_id": comparison_id, "comparison_dimension": dimension, "winner": cmp.winner})
    return results


def recompute_all(db: Database, crawl_run_id: str | None = None) -> dict[str, int]:
    where = "WHERE analysis_target=1" + (" AND crawl_run_id=?" if crawl_run_id else "")
    params = [crawl_run_id] if crawl_run_id else []
    pages = db.query(f"SELECT page_id FROM ci_pages {where}", params)
    page_count = 0
    for p in pages:
        try:
            compute_page_opportunity(db, p["page_id"])
            page_count += 1
        except Exception:
            continue

    kw_where = "WHERE pk.is_primary=1" + (" AND pk.crawl_run_id=?" if crawl_run_id else "")
    keyword_rows = db.query(
        f"SELECT DISTINCT pk.keyword_id, pk.page_id FROM ci_page_keywords pk {kw_where}", params,
    )
    keyword_count = 0
    for row in keyword_rows:
        try:
            compute_keyword_opportunity(db, row["keyword_id"], row["page_id"])
            keyword_count += 1
        except Exception:
            continue
    return {"pages_computed": page_count, "keywords_computed": keyword_count}
