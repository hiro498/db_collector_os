"""PHASE 15 Production Validation orchestration. This module adds no new
analysis technique of its own -- it drives, in order, the exact engines
PHASE 3-11 (crawl/classify/extract/score), PHASE 12 (AI Citation
Readiness), PHASE 13 (external observation), and PHASE 14 (Opportunity /
comparison) already built, and rolls their output into one
domain-wide Target Keyword ranking. Every field that a downstream phase
cannot supply (no external observation imported, no page of ours exists
yet for a keyword) is left NULL/None and reported as such -- never
defaulted to 0 or fabricated.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...database import Database
from ...job_registry import now_iso
from ..ai_search import analyze_ai_page, get_ai_analysis
from ..ai_search.observation.classification import any_cited
from ..ai_search.observation.pipeline import recompute_page_visibility
from ..crawler import CrawlEngine
from ..enums import InputMode
from ..link_analyzer import compute_link_metrics
from ..opportunity.competitor_strength import CompetitorStrengthInputs, compute_competitor_strength
from ..opportunity.config import DEFAULT_WEIGHTS
from ..opportunity.enums import ActionCode, ScoreStatus
from ..opportunity.pipeline import compute_keyword_opportunity
from ..opportunity.repository import KeywordMetricsRepository
from ..repository.core import CrawlRunRepository
from ..url_tools import extract_host, normalize_url
from .aggregation import aggregate_site_keywords
from .blue_ocean import evaluate_blue_ocean_candidate
from .clustering import cluster_keywords
from .config import (
    DEFAULT_MAX_PAGES,
    DEFAULT_RATE_LIMIT_REQUESTS_PER_SECOND,
    DEFAULT_TIE_BREAK,
    TOP_N_CANDIDATES,
    TOP_N_FOR_KPI,
    TOP50_AB_PASS_THRESHOLD,
)
from .content_map import build_content_map
from .enums import AuditClass, KpiSource, ProductionValidationStatus, ValidationRunStatus
from .intent_rollup import rollup_intent
from .money_keyword import classify_money_keyword, money_signals
from .noise import detect_noise, detect_unnatural_ngram
from .quality import compute_audit_class_auto
from .repository import DomainKeywordSummaryRepository, TargetKeywordPriorityRepository, ValidationRunRepository


@dataclass
class ValidationOptions:
    max_pages: int | None = DEFAULT_MAX_PAGES
    rate_limit_requests_per_second: float = DEFAULT_RATE_LIMIT_REQUESTS_PER_SECOND
    output_dir: str | None = None
    our_domain_run_id: str | None = None
    resume_validation_run_id: str | None = None
    user_agent: str = "DBCollectorOS-Validation/1.0"


def _rate_limit_delay(requests_per_second: float) -> float:
    return 1.0 / requests_per_second if requests_per_second > 0 else 1.0


def _page_type_stats(db: Database, crawl_run_id: str) -> dict[str, Any]:
    pages = db.query(
        "SELECT page_type, analysis_target FROM ci_pages WHERE crawl_run_id=?", (crawl_run_id,)
    )
    by_type: dict[str, int] = {}
    analysis_target_pages = 0
    for p in pages:
        by_type[p["page_type"]] = by_type.get(p["page_type"], 0) + 1
        if p["analysis_target"]:
            analysis_target_pages += 1

    url_counts = db.query_one(
        "SELECT COUNT(*) AS total, "
        "SUM(CASE WHEN exclusion_reason IS NOT NULL THEN 1 ELSE 0 END) AS excluded, "
        "SUM(CASE WHEN is_canonical_duplicate=1 THEN 1 ELSE 0 END) AS duplicate, "
        "SUM(CASE WHEN redirect_to IS NOT NULL THEN 1 ELSE 0 END) AS redirected, "
        "SUM(CASE WHEN indexable=0 THEN 1 ELSE 0 END) AS noindexed "
        "FROM ci_crawl_urls WHERE crawl_run_id=?",
        (crawl_run_id,),
    )
    return {
        "pages_total": len(pages),
        "pages_by_type": by_type,
        "analysis_target_pages": analysis_target_pages,
        "excluded_pages": url_counts["excluded"] or 0,
        "duplicate_pages": url_counts["duplicate"] or 0,
        "redirect_pages": url_counts["redirected"] or 0,
        "noindex_pages": url_counts["noindexed"] or 0,
    }


def _run_ai_search_analysis(db: Database, crawl_run_id: str) -> list[str]:
    """PHASE 12 integration (spec section 15): readiness only, never a
    citation claim."""
    errors = []
    pages = db.query("SELECT page_id FROM ci_pages WHERE crawl_run_id=? AND analysis_target=1", (crawl_run_id,))
    for p in pages:
        try:
            if get_ai_analysis(db, p["page_id"]) is None:
                analyze_ai_page(db, p["page_id"])
        except Exception as exc:  # noqa: BLE001 -- one page's failure must not abort the run
            errors.append(f"ai_analyze failed for page {p['page_id']}: {exc}")
    return errors


def _run_observation_rollup(db: Database, crawl_run_id: str) -> list[str]:
    """PHASE 13 integration (spec section 16): rolls up whatever
    observations already exist (typically none for a freshly-crawled
    competitor domain, until offline-imported) -- never forces a network
    fetch, never defaults an unobserved field to 0."""
    errors = []
    pages = db.query("SELECT page_id FROM ci_pages WHERE crawl_run_id=? AND analysis_target=1", (crawl_run_id,))
    for p in pages:
        try:
            recompute_page_visibility(db, p["page_id"])
        except Exception as exc:  # noqa: BLE001
            errors.append(f"observation rollup failed for page {p['page_id']}: {exc}")
    return errors


def _best_competitor_page_for_keyword(db: Database, crawl_run_id: str, keyword_id: str) -> dict[str, Any] | None:
    rows = db.query(
        "SELECT pk.page_id, pk.score FROM ci_page_keywords pk WHERE pk.crawl_run_id=? AND pk.keyword_id=? "
        "ORDER BY pk.score DESC LIMIT 1",
        (crawl_run_id, keyword_id),
    )
    if not rows:
        return None
    return db.query_one("SELECT * FROM ci_pages WHERE page_id=?", (rows[0]["page_id"],))


def _our_page_for_keyword(db: Database, our_domain_run_id: str, keyword_id: str) -> str | None:
    row = db.query_one(
        "SELECT page_id FROM ci_page_keywords WHERE crawl_run_id=? AND keyword_id=? ORDER BY score DESC LIMIT 1",
        (our_domain_run_id, keyword_id),
    )
    return row["page_id"] if row else None


def _competitor_usage_strength(db: Database, page: dict[str, Any], link_cache: dict[str, Any]) -> float | None:
    ai_analysis = get_ai_analysis(db, page["page_id"])
    visibility = db.query_one("SELECT * FROM ci_ai_page_visibility WHERE page_id=?", (page["page_id"],))
    crawl_run_id = page["crawl_run_id"]
    if crawl_run_id not in link_cache:
        link_cache[crawl_run_id] = compute_link_metrics(db, crawl_run_id)
    lm = link_cache[crawl_run_id].get(page["page_id"], {})
    ai_cited = None
    if visibility:
        ai_cited = any_cited(
            None if visibility["aio_cited"] is None else bool(visibility["aio_cited"]),
            None if visibility["ai_mode_cited"] is None else bool(visibility["ai_mode_cited"]),
        )
    inputs = CompetitorStrengthInputs(
        organic_rank=visibility["organic_rank"] if visibility else None, ai_cited=ai_cited,
        subtopic_count=ai_analysis["subtopic_count"] if ai_analysis else 0,
        related_question_count=ai_analysis["related_question_count"] if ai_analysis else 0,
        entity_coverage_count=ai_analysis["entity_coverage_count"] if ai_analysis else 0,
        proprietary_information_score=ai_analysis["proprietary_information_score"] if ai_analysis else None,
        evidence_freshness_score=ai_analysis["evidence_freshness_score"] if ai_analysis else None,
        inbound_link_count=lm.get("inbound_count", 0), pagerank=lm.get("pagerank", 0.0),
        monetization_score=page.get("monetization_score"),
    )
    return compute_competitor_strength(inputs).competitor_strength_score


def run_validation(db: Database, target_url: str, options: ValidationOptions | None = None) -> str:
    """Runs (or resumes) one end-to-end Production Validation and returns
    its validation_run_id. Raises nothing on a per-page/per-keyword
    failure -- those are collected into the run's `errors`/`warnings`
    summary lists instead, per spec section 36 ("run全体が不必要にクラッシュ
    しないこと")."""
    options = options or ValidationOptions()
    run_repo = ValidationRunRepository(db)
    warnings: list[str] = []
    errors: list[str] = []

    if options.resume_validation_run_id:
        validation_run_id = options.resume_validation_run_id
        existing = run_repo.get(validation_run_id)
        if not existing:
            raise ValueError(f"no such validation_run_id to resume: {validation_run_id}")
        crawl_run_id = existing["crawl_run_id"]
    else:
        validation_run_id = run_repo.create(
            target_url, options.max_pages, _rate_limit_delay(options.rate_limit_requests_per_second),
            options.output_dir, options.our_domain_run_id,
        )
        crawl_run_id = None

    engine = CrawlEngine(
        db, user_agent=options.user_agent, rate_limit_delay_seconds=_rate_limit_delay(options.rate_limit_requests_per_second),
    )

    try:
        if crawl_run_id:
            engine.resume(crawl_run_id, max_pages=options.max_pages)
        else:
            crawl_run_id = engine.start_affiliate_domain(
                target_url, requested_mode=InputMode.AFFILIATE_DOMAIN, max_pages=options.max_pages,
            )
        run = CrawlRunRepository(db).get(crawl_run_id)
        run_repo.set_crawl_run(validation_run_id, crawl_run_id, run["domain_id"])
    except Exception as exc:  # noqa: BLE001 -- crawl failure ends the run, but must still report cleanly
        run_repo.complete(
            validation_run_id, ValidationRunStatus.FAILED, ProductionValidationStatus.FAIL, None, False,
            {"error": str(exc)}, error_message=str(exc),
        )
        return validation_run_id

    if not run.get("converged"):
        warnings.append(
            "crawl did not fully converge within this run (max_pages cap or safe-stop) -- "
            "results reflect a partial site sample"
        )

    page_stats = _page_type_stats(db, crawl_run_id)
    if page_stats["pages_total"] == 0:
        run_repo.complete(
            validation_run_id, ValidationRunStatus.FAILED, ProductionValidationStatus.FAIL, None, False,
            {"error": "no pages fetched", **page_stats}, error_message="no pages fetched",
        )
        return validation_run_id

    errors.extend(_run_ai_search_analysis(db, crawl_run_id))
    obs_errors = _run_observation_rollup(db, crawl_run_id)
    errors.extend(obs_errors)
    has_any_observation = db.query_one(
        "SELECT COUNT(*) AS n FROM ci_ai_page_visibility v JOIN ci_pages p ON p.page_id=v.page_id "
        "WHERE p.crawl_run_id=? AND (v.organic_rank IS NOT NULL OR v.aio_cited IS NOT NULL "
        "OR v.ai_mode_cited IS NOT NULL)",
        (crawl_run_id,),
    )["n"] > 0
    if not has_any_observation:
        warnings.append(
            "no external SERP/AIO/AI Mode observation data found for this domain -- "
            "organic_rank/aio_cited/ai_mode_cited are NOT_OBSERVED for every keyword (see `ci observation import`)"
        )
    if not options.our_domain_run_id:
        warnings.append(
            "no --our-domain-run provided -- opportunity_score/content_gap_score are NOT_ENOUGH_DATA "
            "for every keyword (PHASE 14 needs an existing page of ours to compare against)"
        )

    summaries = aggregate_site_keywords(db, crawl_run_id)
    if not summaries:
        run_repo.complete(
            validation_run_id, ValidationRunStatus.FAILED, ProductionValidationStatus.FAIL, None, False,
            {"error": "no keywords extracted", **page_stats}, error_message="no keywords extracted",
        )
        return validation_run_id

    normalized_keywords = [s["normalized_keyword"] for s in summaries]
    cluster_assignment = cluster_keywords(normalized_keywords)
    cluster_sizes: dict[str, int] = {}
    for kw, cluster_id in cluster_assignment.items():
        cluster_sizes[cluster_id] = cluster_sizes.get(cluster_id, 0) + 1

    keyword_classes = {
        r["normalized_keyword"]: r["keyword_class"]
        for r in db.query(
            "SELECT normalized_keyword, keyword_class FROM ci_keywords WHERE normalized_keyword IN ({})".format(
                ",".join("?" for _ in normalized_keywords)
            ),
            normalized_keywords,
        )
    } if normalized_keywords else {}

    normalized_keyword_set = set(normalized_keywords)
    money_classes: dict[str, str | None] = {}
    summary_rows: list[dict[str, Any]] = []
    for s in summaries:
        normalized = s["normalized_keyword"]
        is_noise, noise_reason = detect_noise(s["keyword"])
        if not is_noise:
            is_ngram_noise, ngram_reason = detect_unnatural_ngram(normalized, normalized_keyword_set - {normalized})
            if is_ngram_noise:
                is_noise, noise_reason = is_ngram_noise, ngram_reason
        primary_intent, secondary_intents, intent_confidence = rollup_intent(s["intents"])
        signals = money_signals(s["modifiers"])
        money_class = classify_money_keyword(s["avg_commercial_score"])
        money_classes[normalized] = money_class
        cluster_id = cluster_assignment.get(normalized, normalized)
        audit_class_auto = compute_audit_class_auto(s["best_keyword_score"], is_noise, s["token_count"])

        summary_rows.append({
            **s,
            "cluster_id": cluster_id, "cluster_is_representative": cluster_id == normalized,
            "primary_intent": primary_intent, "secondary_intents": secondary_intents,
            "intent_confidence": intent_confidence, "commercial_score": s["avg_commercial_score"],
            **signals, "affiliate_relevance": s["avg_commercial_score"], "monetization_score": None,
            "money_keyword_class": money_class, "is_noise": is_noise, "noise_reason": noise_reason,
            "audit_class_auto": audit_class_auto, "audit_class": None, "audit_note": None,
        })

    DomainKeywordSummaryRepository(db).replace_all(validation_run_id, summary_rows)

    content_map_rows = build_content_map(summaries, keyword_classes, money_classes, cluster_sizes)

    # ---- Target Keyword ranking (spec sections 15-19) ----
    demand_repo = KeywordMetricsRepository(db)
    link_cache: dict[str, Any] = {}
    priority_rows: list[dict[str, Any]] = []
    candidates = [r for r in summary_rows if r["cluster_is_representative"] and not r["is_noise"]]

    for r in candidates:
        keyword_id = r["keyword_id"]
        best_competitor_page = _best_competitor_page_for_keyword(db, crawl_run_id, keyword_id) if keyword_id else None
        ai_analysis = get_ai_analysis(db, best_competitor_page["page_id"]) if best_competitor_page else None
        visibility = (
            db.query_one("SELECT * FROM ci_ai_page_visibility WHERE page_id=?", (best_competitor_page["page_id"],))
            if best_competitor_page else None
        )
        competitor_strength = (
            _competitor_usage_strength(db, best_competitor_page, link_cache) if best_competitor_page else None
        )

        our_page_id = (
            _our_page_for_keyword(db, options.our_domain_run_id, keyword_id)
            if options.our_domain_run_id and keyword_id else None
        )

        content_gap_score = opportunity_score = score_status = confidence_label = None
        confidence_value = top_reason_code = top_reason_text = recommended_action = None
        if our_page_id and best_competitor_page:
            try:
                opp = compute_keyword_opportunity(
                    db, keyword_id, our_page_id, [best_competitor_page["page_id"]], DEFAULT_WEIGHTS,
                )
                content_gap_score = opp["content_gap_score"]
                opportunity_score = opp["overall_opportunity_score"]
                score_status = opp["score_status"]
                confidence_label = opp["confidence_label"]
                confidence_value = opp["confidence_value"]
                from ..opportunity.pipeline import get_opportunity_detail
                detail = get_opportunity_detail(db, opp["opportunity_id"])
                if detail["reasons"]:
                    top_reason_code = detail["reasons"][0]["reason_code"]
                    top_reason_text = detail["reasons"][0]["reason_text"]
                if detail["actions"]:
                    recommended_action = detail["actions"][0]["action_code"]
            except Exception as exc:  # noqa: BLE001
                errors.append(f"opportunity computation failed for keyword {keyword_id}: {exc}")
                score_status = ScoreStatus.NOT_ENOUGH_DATA
        else:
            score_status = ScoreStatus.NOT_ENOUGH_DATA
            confidence_label, confidence_value = "LOW", 0.1
            recommended_action = ActionCode.CREATE_NEW_PAGE
            top_reason_text = "no existing page in our domain targets this keyword yet"

        metrics = demand_repo.latest_for_query(r["keyword"])
        demand_status = "OBSERVED" if metrics else "UNAVAILABLE"

        competitor_page_count = db.query_one(
            "SELECT COUNT(DISTINCT page_id) AS n FROM ci_page_keywords WHERE crawl_run_id=? AND keyword_id=?",
            (crawl_run_id, keyword_id),
        )["n"] if keyword_id else 0

        blue_ocean_candidate, blue_ocean_status = evaluate_blue_ocean_candidate(
            opportunity_score, r["commercial_score"], content_gap_score,
            ai_analysis["proprietary_information_score"] if ai_analysis else None,
            demand_observed=bool(metrics), competitor_count=competitor_page_count,
        )

        priority_rows.append({
            "keyword": r["keyword"], "normalized_keyword": r["normalized_keyword"], "keyword_id": keyword_id,
            "intent": r["primary_intent"], "commercial_score": r["commercial_score"],
            "money_keyword_class": r["money_keyword_class"],
            "competitor_usage_strength": competitor_strength, "competitor_page_count": competitor_page_count,
            "best_competitor_page_id": best_competitor_page["page_id"] if best_competitor_page else None,
            "best_competitor_page_url": best_competitor_page["url"] if best_competitor_page else None,
            "best_competitor_score": r["best_keyword_score"],
            "ai_readiness": ai_analysis["ai_citation_readiness_score"] if ai_analysis else None,
            "organic_rank": visibility["organic_rank"] if visibility else None,
            "aio_cited": visibility["aio_cited"] if visibility else None,
            "ai_mode_cited": visibility["ai_mode_cited"] if visibility else None,
            "citation_frequency": (
                (visibility["aio_citation_frequency"] if visibility["aio_citation_frequency"] is not None
                 else visibility["ai_mode_citation_frequency"]) if visibility else None
            ),
            "fanout_visibility": visibility["fanout_visibility_rate"] if visibility else None,
            "content_gap_score": content_gap_score, "opportunity_score": opportunity_score,
            "score_status": score_status, "confidence_label": confidence_label, "confidence_value": confidence_value,
            "top_reason_code": top_reason_code, "top_reason_text": top_reason_text,
            "recommended_action": recommended_action, "demand_status": demand_status,
            "search_volume": metrics["search_volume"] if metrics else None,
            "trend": metrics["trend"] if metrics else None, "cpc": metrics["cpc"] if metrics else None,
            "competition": metrics["competition"] if metrics else None,
            "blue_ocean_candidate": blue_ocean_candidate, "blue_ocean_candidate_status": blue_ocean_status,
        })

    def _sort_key(row: dict[str, Any]) -> tuple:
        key = [(-1 if row["opportunity_score"] is None else 1, row["opportunity_score"] or 0.0)]
        for f in DEFAULT_TIE_BREAK.fields:
            value = row.get(f)
            key.append((-1 if value is None else 1, value or 0.0))
        return tuple(key)

    priority_rows.sort(key=_sort_key, reverse=True)
    for i, row in enumerate(priority_rows, start=1):
        row["priority_rank"] = i

    TargetKeywordPriorityRepository(db).replace_all(validation_run_id, priority_rows)

    # ---- TOP50/TOP100 KPI (spec sections 10, 32) ----
    quality_ranked = sorted(candidates, key=lambda r: r["best_keyword_score"], reverse=True)
    top_n = quality_ranked[:TOP_N_FOR_KPI]
    human_audited = [r for r in top_n if r.get("audit_class")]
    kpi_source = KpiSource.HUMAN_AUDITED if len(human_audited) == len(top_n) and top_n else KpiSource.AUTO_QUALITY_RATE
    grade_field = "audit_class" if kpi_source == KpiSource.HUMAN_AUDITED else "audit_class_auto"
    top50_ab_rate = (
        sum(1 for r in top_n if r.get(grade_field) in AuditClass.ACQUISITION) / len(top_n) if top_n else None
    )
    top100_count = len(quality_ranked[:TOP_N_CANDIDATES])

    if top50_ab_rate is not None and top50_ab_rate < TOP50_AB_PASS_THRESHOLD:
        warnings.append(f"TOP50 A+B rate {top50_ab_rate:.0%} is below the {TOP50_AB_PASS_THRESHOLD:.0%} PASS threshold")

    # ---- production_validation_status (spec section 25) ----
    if top50_ab_rate is None:
        status = ProductionValidationStatus.FAIL
        errors.append("could not compute TOP50 A+B rate (fewer than 1 quality-ranked candidate)")
    elif top50_ab_rate < TOP50_AB_PASS_THRESHOLD:
        status = ProductionValidationStatus.CONDITIONAL_PASS
    else:
        status = ProductionValidationStatus.PASS

    integrity_ok, integrity_detail = db.integrity_check()
    if not integrity_ok:
        status = ProductionValidationStatus.FAIL
        errors.append(f"DB integrity check failed: {integrity_detail}")

    completed_at = now_iso()
    summary = {
        "target_domain": extract_host(normalize_url(target_url)),
        "started_at": run_repo.get(validation_run_id)["started_at"],
        "completed_at": completed_at,
        "pages_discovered": db.query_one(
            "SELECT COUNT(*) AS n FROM ci_crawl_urls WHERE crawl_run_id=?", (crawl_run_id,)
        )["n"],
        "pages_fetched": page_stats["pages_total"],
        "pages_analyzed": page_stats["analysis_target_pages"],
        "pages_excluded": page_stats["excluded_pages"],
        "pages_by_type": page_stats["pages_by_type"],
        "duplicate_pages": page_stats["duplicate_pages"],
        "redirect_pages": page_stats["redirect_pages"],
        "noindex_pages": page_stats["noindex_pages"],
        "keywords_total": len(summary_rows),
        "keyword_clusters": len(cluster_sizes),
        "top50_ab_rate": top50_ab_rate,
        "top50_ab_rate_source": kpi_source,
        "top100_count": top100_count,
        "commercial_keywords": sum(1 for r in summary_rows if r["money_keyword_class"] in ("HIGH", "MEDIUM")),
        "high_opportunity_keywords": sum(
            1 for r in priority_rows if r["opportunity_score"] is not None and r["opportunity_score"] >= 65.0
        ),
        "blue_ocean_candidates": sum(1 for r in priority_rows if r["blue_ocean_candidate"] is True),
        "errors": errors,
        "warnings": warnings,
        "production_validation_status": status,
        "content_map": content_map_rows,
    }

    run_repo.complete(
        validation_run_id, ValidationRunStatus.COMPLETED, status, top50_ab_rate,
        kpi_source == KpiSource.HUMAN_AUDITED, summary,
    )
    return validation_run_id
