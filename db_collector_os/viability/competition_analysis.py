"""Phase 2: turn one keyword's SERP results into a WEAK/MEDIUM/STRONG
competition strength, and roll many keywords' strengths up into a theme-level
summary (weak/medium/strong ratios, winnable vs. unwinnable demand).

Design point from the spec: a big-name domain ranking is not itself
disqualifying -- what matters is whether the *result actually satisfies the
searcher's intent* (a dedicated, DB-shaped page) or is just incidental
(a generic homepage, an unrelated article). `title_match`/`db_type_page`/
`intent_satisfied` drive the score much more than raw domain fame, and every
one of those can be supplied as a manual/LLM-judged override per result
(via SERP CSV import) instead of relying purely on the crude heuristic
classifier below -- see serp_sources/csv_import.py's column list.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from .config import ViabilityConfig

SITE_TYPES = (
    "major_corp",
    "major_ec",
    "expert_media",
    "portal",
    "specialty_store",
    "small_business",
    "personal",
    "unknown",
)

# A tiny, extensible seed list for the heuristic fallback classifier. Real
# accuracy is expected to come from manual/LLM classification supplied via
# CSV import (site_type column) -- this only keeps the automatic path from
# guessing "unknown" for the most obvious, universally recognizable majors.
_KNOWN_MAJOR_EC_DOMAINS = {"amazon.co.jp", "rakuten.co.jp", "yahoo.co.jp", "shopping.yahoo.co.jp", "mercari.com"}
_PORTAL_HINTS = ("まとめ", "一覧", "比較", "ランキング")
_LISTING_URL_HINTS = ("/list", "/category", "/search", "/area/", "/tag/")
_PRODUCT_URL_HINTS = ("/item/", "/product", "/goods/")


def classify_site_type(domain: str | None, title: str | None) -> str:
    domain = (domain or "").lower()
    if domain in _KNOWN_MAJOR_EC_DOMAINS:
        return "major_ec"
    return "unknown"


def classify_page_type(url: str | None, title: str | None) -> str:
    url = (url or "").lower()
    title = title or ""
    if any(hint in url for hint in _LISTING_URL_HINTS) or any(hint in title for hint in _PORTAL_HINTS):
        return "listing"
    if any(hint in url for hint in _PRODUCT_URL_HINTS):
        return "product"
    return "article"


def classify_title_match(title: str | None, query: str) -> str:
    if not title:
        return "none"
    title_norm = "".join(title.split())
    query_norm = "".join(query.split())
    if query_norm and query_norm == title_norm:
        return "exact"
    tokens = [t for t in query.split() if t]
    if tokens and all(t in title for t in tokens):
        return "exact"
    if tokens and any(t in title for t in tokens):
        return "partial"
    return "none"


def _enrich_result(result: dict[str, Any], query: str) -> dict[str, Any]:
    """Fill in any classification field left blank (None) by a manual
    override with the heuristic fallback. Fields explicitly provided
    (e.g. from CSV import / LLM judgement) always win.
    """
    out = dict(result)
    out["site_type"] = out.get("site_type") or classify_site_type(out.get("domain"), out.get("title"))
    out["page_type"] = out.get("page_type") or classify_page_type(out.get("url"), out.get("title"))
    out["title_match"] = out.get("title_match") or classify_title_match(out.get("title"), query)
    if out.get("db_type_page") is None:
        out["db_type_page"] = out["page_type"] == "listing" and out["title_match"] in ("exact", "partial")
    if out.get("intent_satisfied") is None:
        out["intent_satisfied"] = bool(out["db_type_page"]) or out["title_match"] == "exact"
    return out


def score_keyword_competition(
    query: str, results: list[dict[str, Any]], config: ViabilityConfig
) -> dict[str, Any]:
    """`results` are plain dicts (rank/title/url/domain/snippet + optional
    classification overrides), rank-ordered. Returns a dict ready for
    ViabilityStore.save_keyword_competition().
    """
    cc = config.competition_classification
    considered_n = cc.get("results_considered", 5)
    site_weight = cc.get("site_type_weight", {})
    page_adj = cc.get("page_type_adjustment", {})
    db_bonus = cc.get("db_type_page_bonus", 20)
    exact_bonus = cc.get("title_exact_match_bonus", 12)
    partial_bonus = cc.get("title_partial_match_bonus", 4)
    relief = cc.get("intent_unsatisfied_relief", 25)
    strong_min = cc.get("strong_min_score", 60)
    medium_min = cc.get("medium_min_score", 32)

    considered = [_enrich_result(r, query) for r in sorted(results, key=lambda r: r.get("rank", 999))[:considered_n]]

    if not considered:
        return {
            "strength": "WEAK",
            "strength_score": 0.0,
            "intent_satisfied": False,
            "db_type_page_present": False,
            "site_type_summary": {},
            "reasoning": "検索結果が0件のため、専用ページが存在せず攻略余地ありと判断 (WEAK)。",
        }

    per_result_scores = []
    for r in considered:
        score = site_weight.get(r["site_type"], site_weight.get("unknown", 35))
        score += page_adj.get(r["page_type"], 0)
        if r["title_match"] == "exact":
            score += exact_bonus
        elif r["title_match"] == "partial":
            score += partial_bonus
        if r["db_type_page"]:
            score += db_bonus
        if not r["intent_satisfied"]:
            score -= relief
        per_result_scores.append(max(0.0, min(100.0, score)))

    strength_score = round(sum(per_result_scores) / len(per_result_scores), 1)
    if strength_score >= strong_min:
        strength = "STRONG"
    elif strength_score >= medium_min:
        strength = "MEDIUM"
    else:
        strength = "WEAK"

    intent_satisfied_any = any(r["intent_satisfied"] for r in considered)
    db_type_page_present = any(r["db_type_page"] for r in considered)
    site_type_summary = dict(Counter(r["site_type"] for r in considered))

    if intent_satisfied_any and db_type_page_present:
        reasoning = (
            f"上位{len(considered)}件中に検索意図を満たす専用ページ (DB型ページ) が存在し、"
            f"strength_score={strength_score} -> {strength}。"
        )
    else:
        reasoning = (
            f"上位{len(considered)}件は検索意図を十分満たしていない (専用ページなし) ため攻略余地あり。"
            f"strength_score={strength_score} -> {strength}。"
        )

    return {
        "strength": strength,
        "strength_score": strength_score,
        "intent_satisfied": intent_satisfied_any,
        "db_type_page_present": db_type_page_present,
        "site_type_summary": site_type_summary,
        "reasoning": reasoning,
    }


def summarize_theme_competition(
    keyword_competition_rows: list[dict[str, Any]], keyword_volume_by_candidate: dict[str, int]
) -> dict[str, Any]:
    """Roll up per-keyword competition rows (ViabilityStore.list_keyword_competition_for_run
    output, each carrying `candidate_id`/`strength`) into theme-level ratios
    and winnable/unwinnable demand -- the spec's headline metric: how much of
    the demand that exists is actually attackable.
    """
    n = len(keyword_competition_rows)
    if n == 0:
        return {
            "weak_ratio": None, "medium_ratio": None, "strong_ratio": None,
            "winnable_demand": 0, "unwinnable_demand": 0,
        }

    counts = Counter(r["strength"] for r in keyword_competition_rows)
    winnable = 0
    unwinnable = 0
    for r in keyword_competition_rows:
        volume = keyword_volume_by_candidate.get(r["candidate_id"], 0) or 0
        if r["strength"] in ("WEAK", "MEDIUM"):
            winnable += volume
        else:
            unwinnable += volume

    return {
        "weak_ratio": round(counts.get("WEAK", 0) / n, 3),
        "medium_ratio": round(counts.get("MEDIUM", 0) / n, 3),
        "strong_ratio": round(counts.get("STRONG", 0) / n, 3),
        "winnable_demand": winnable,
        "unwinnable_demand": unwinnable,
    }
