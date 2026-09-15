"""End-to-end PHASE 14 tests, including the spec section 29/30 realistic
fixture: 3 competitor pages + 1 of our own, sharing a keyword, with real
organic/AIO/AI-Mode/fan-out observations -- verifying the computed
Opportunity matches human intuition (Competitor A: organic-strong/AI-weak;
Competitor B: strong all-round benchmark; Our Page: High Readiness/Not
Cited -> high AI Opportunity), not just that the pipeline runs.
"""
from __future__ import annotations

import responses

from db_collector_os.database import new_id
from db_collector_os.job_registry import now_iso
from db_collector_os.competitive_intelligence.ai_search import analyze_ai_page, recompute_ai_analysis
from db_collector_os.competitive_intelligence.ai_search.observation.repository import (
    AioObservationRepository, AiModeObservationRepository, FanoutObservationRepository, SerpObservationRepository,
)
from db_collector_os.competitive_intelligence.ai_search.observation.pipeline import recompute_page_visibility
from db_collector_os.competitive_intelligence.ai_search.repository import AiFanoutQueryRepository
from db_collector_os.competitive_intelligence.crawler import CrawlEngine
from db_collector_os.competitive_intelligence.repository.pages import PageRepository
from db_collector_os.competitive_intelligence.opportunity import (
    compare_domains, compare_keywords, compare_pages, compute_keyword_opportunity, compute_page_opportunity,
    get_opportunity, get_opportunity_detail, recompute_all,
)

QUERY = "おすすめ 睡眠グッズ"

HTML_A = f"""<!doctype html><html><head><title>{QUERY}まとめ</title>
<link rel="canonical" href="https://competitor-a.example/page/"></head><body>
<main><h1>{QUERY}まとめ</h1><p>{QUERY}について簡単に紹介します。</p></main>
</body></html>"""

HTML_B = f"""<!doctype html><html><head><title>{QUERY}【独自調査】</title>
<link rel="canonical" href="https://competitor-b.example/page/"></head><body>
<main><h1>{QUERY}【独自調査】</h1>
<p>編集部が実際に42点を試し、独自調査した結果をもとにランキングを作成しました。調査方法は実機レビューです。
同ジャンル500点中上位3%です。レビュー数は120件から480件に増加しました。順位も18位から3位に上昇しています。
価格帯・評価・特徴も含めて詳しく比較しており、購入前の参考情報として役立つ内容を目指して作成しています。</p>
<table><caption>比較表</caption><tr><th>商品</th><th>評価</th><th>価格</th></tr>
<tr><td>商品A</td><td>4.5</td><td>3000円</td></tr><tr><td>商品B</td><td>4.2</td><td>2500円</td></tr></table>
<h2>選び方のポイント</h2><h2>よくある質問</h2>
<dl><dt>返品は可能ですか？</dt><dd>可能です。</dd></dl>
</main></body></html>"""

HTML_OURS = f"""<!doctype html><html><head><title>{QUERY}【2026年最新・独自調査】</title>
<link rel="canonical" href="https://our-site.example/page/"></head><body>
<main><h1>{QUERY}【2026年最新版・独自調査】</h1>
<p>編集部が実際に80点を試し、独自調査・n=80のアンケート調査を実施した結果をもとに作成しました。
同ジャンル1,000点中上位1%です。レビュー数は300件から900件に増加しました。順位も25位から2位に上昇しています。
調査方法は覆面調査です。サンプルサイズはn=80です。価格帯・特徴・専門家コメントも含めて徹底的に比較しています。</p>
<table><caption>徹底比較表</caption><tr><th>商品</th><th>評価</th><th>価格</th><th>特徴</th></tr>
<tr><td>商品A</td><td>4.8</td><td>3200円</td><td>速効性</td></tr>
<tr><td>商品B</td><td>4.6</td><td>2800円</td><td>持続性</td></tr>
<tr><td>商品C</td><td>4.3</td><td>2000円</td><td>コスパ</td></tr></table>
<h2>選び方のポイント</h2><h2>よくある質問</h2><h2>専門家のコメント</h2>
<dl><dt>返品は可能ですか？</dt><dd>可能です。</dd></dl><dl><dt>効果はどれくらいで出ますか？</dt><dd>個人差があります。</dd></dl>
</main></body></html>"""


def _ensure_primary_keyword(db, page_id, crawl_run_id, keyword_text, commercial_score=70):
    existing = db.query_one("SELECT keyword_id FROM ci_keywords WHERE normalized_keyword=?", (keyword_text,))
    keyword_id = existing["keyword_id"] if existing else new_id("kw_")
    if not existing:
        db.execute(
            "INSERT INTO ci_keywords (keyword_id, keyword, normalized_keyword, token_count, branded_type, "
            "is_local, keyword_class, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (keyword_id, keyword_text, keyword_text, 2, "non_branded", 0, "mid_tail", now_iso(), now_iso()),
        )
    already = db.query_one(
        "SELECT page_keyword_id FROM ci_page_keywords WHERE page_id=? AND keyword_id=?", (page_id, keyword_id)
    )
    if already:
        db.execute("UPDATE ci_page_keywords SET is_primary=1, score=100, commercial_score=? WHERE page_keyword_id=?",
                   (commercial_score, already["page_keyword_id"]))
    else:
        db.execute(
            "INSERT INTO ci_page_keywords (page_keyword_id, page_id, keyword_id, crawl_run_id, score, "
            "commercial_score, importance, is_primary, computed_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (new_id("pk_"), page_id, keyword_id, crawl_run_id, 100, commercial_score, "primary", 1, now_iso()),
        )
    return keyword_id


def _crawl(db, html, url):
    with responses.RequestsMock() as rsps:
        rsps.add(responses.GET, url, body=html, content_type="text/html")
        engine = CrawlEngine(db, user_agent="TestBot/1.0")
        run_id = engine.start_advertiser_lp(url, requested_mode="advertiser_lp")
    return PageRepository(db).list_for_run(run_id, limit=1)[0]


def _build_fixture(db):
    """Builds the full spec section 29/30 scenario, returning
    (page_a, page_b, page_ours, keyword_id)."""
    page_a = _crawl(db, HTML_A, "https://competitor-a.example/page/")
    page_b = _crawl(db, HTML_B, "https://competitor-b.example/page/")
    page_ours = _crawl(db, HTML_OURS, "https://our-site.example/page/")

    keyword_id = None
    for p in (page_a, page_b, page_ours):
        analyze_ai_page(db, p["page_id"])
        keyword_id = _ensure_primary_keyword(db, p["page_id"], p["crawl_run_id"], QUERY)
        recompute_ai_analysis(db, p["page_id"])

    serp_repo = SerpObservationRepository(db)
    serp_repo.record(
        query=QUERY, country="JP", language="ja", device="desktop", observed_at="2026-01-01T00:00:00Z",
        provider="manual", status="available",
        results=[
            {"result_position": 1, "result_url": page_a["url"], "normalized_url": page_a["normalized_url"], "result_domain": "competitor-a.example"},
            {"result_position": 8, "result_url": page_b["url"], "normalized_url": page_b["normalized_url"], "result_domain": "competitor-b.example"},
            {"result_position": 15, "result_url": page_ours["url"], "normalized_url": page_ours["normalized_url"], "result_domain": "our-site.example"},
        ],
    )
    AioObservationRepository(db).record(
        query=QUERY, country="JP", language="ja", device="desktop", observed_at="2026-01-01T00:00:00Z",
        provider="manual", status="available", aio_present=True,
        citations=[{"citation_position": 1, "citation_url": page_b["url"], "normalized_url": page_b["normalized_url"], "citation_domain": "competitor-b.example"}],
    )
    AiModeObservationRepository(db).record(
        query=QUERY, country="JP", language="ja", device="desktop", observed_at="2026-01-01T00:00:00Z",
        provider="manual", status="available",
        citations=[{"citation_position": 1, "citation_url": page_b["url"], "normalized_url": page_b["normalized_url"], "citation_domain": "competitor-b.example"}],
    )
    for p in (page_a, page_b, page_ours):
        recompute_page_visibility(db, p["page_id"])

    fanout = AiFanoutQueryRepository(db).list_for_page(page_ours["page_id"])
    if fanout:
        FanoutObservationRepository(db).record(
            fanout_query_id=fanout[0]["fanout_query_id"], parent_query=QUERY, fanout_query=fanout[0]["subquery_text"],
            fanout_intent=fanout[0]["intent_class"], country="JP", language="ja", device="desktop",
            observed_at="2026-01-01T00:00:00Z", provider="manual", status="available",
            target_page_id=page_ours["page_id"], target_rank=25, target_cited=False, result_urls=[],
        )

    return page_a, page_b, page_ours, keyword_id


def test_fixture_readiness_vs_reality_matches_human_intuition(db):
    page_a, page_b, page_ours, _ = _build_fixture(db)
    vis_a = db.query_one("SELECT * FROM ci_ai_page_visibility WHERE page_id=?", (page_a["page_id"],))
    vis_b = db.query_one("SELECT * FROM ci_ai_page_visibility WHERE page_id=?", (page_b["page_id"],))
    vis_ours = db.query_one("SELECT * FROM ci_ai_page_visibility WHERE page_id=?", (page_ours["page_id"],))
    assert vis_a["organic_rank"] == 1 and vis_a["aio_cited"] == 0
    assert vis_b["aio_cited"] == 1 and vis_b["ai_mode_cited"] == 1
    assert vis_ours["readiness_vs_reality_class"] == "B", "our page must be High Readiness / Not Cited"


def test_page_opportunity_surfaces_high_ai_opportunity_for_our_page(db):
    page_a, page_b, page_ours, _ = _build_fixture(db)
    result = compute_page_opportunity(db, page_ours["page_id"], [page_a["page_id"], page_b["page_id"]])
    assert result["ai_opportunity_score"] >= 80.0
    assert result["best_competitor_page_id"] == page_b["page_id"], "Competitor B is the strongest benchmark"
    assert result["our_rank"] == 15
    assert result["best_competitor_rank"] == 1


def test_page_opportunity_reason_engine_surfaces_high_readiness_not_cited(db):
    page_a, page_b, page_ours, _ = _build_fixture(db)
    result = compute_page_opportunity(db, page_ours["page_id"], [page_a["page_id"], page_b["page_id"]])
    detail = get_opportunity_detail(db, result["opportunity_id"])
    codes = {r["reason_code"] for r in detail["reasons"]}
    assert "HIGH_READINESS_NOT_CITED" in codes


def test_page_opportunity_components_are_individually_stored(db):
    page_a, page_b, page_ours, _ = _build_fixture(db)
    result = compute_page_opportunity(db, page_ours["page_id"], [page_a["page_id"], page_b["page_id"]])
    detail = get_opportunity_detail(db, result["opportunity_id"])
    names = {c["component_name"] for c in detail["components"]}
    from db_collector_os.competitive_intelligence.opportunity.config import COMPONENT_NAMES
    assert names == set(COMPONENT_NAMES)
    for c in detail["components"]:
        if c["availability"] == "UNAVAILABLE":
            assert c["value"] is None, "UNAVAILABLE components must never carry a fabricated value"


def test_page_opportunity_score_status_and_confidence_are_consistent(db):
    page_a, page_b, page_ours, _ = _build_fixture(db)
    result = compute_page_opportunity(db, page_ours["page_id"], [page_a["page_id"], page_b["page_id"]])
    assert result["score_status"] in ("COMPLETE", "PARTIAL", "INTERNAL_ONLY", "NOT_ENOUGH_DATA")
    assert 0.0 <= result["confidence_value"] <= 1.0
    assert result["confidence_label"] in ("HIGH", "MEDIUM", "LOW")


def test_page_opportunity_unknown_page_raises(db):
    import pytest
    with pytest.raises(ValueError):
        compute_page_opportunity(db, "no-such-page")


def test_keyword_opportunity_requires_explicit_our_page(db):
    """spec: never silently guess which page is 'ours' -- our_page_id is a
    required, explicit argument."""
    import pytest
    page_a, page_b, page_ours, keyword_id = _build_fixture(db)
    with pytest.raises(TypeError):
        compute_keyword_opportunity(db, keyword_id)  # missing required our_page_id


def test_keyword_opportunity_end_to_end(db):
    page_a, page_b, page_ours, keyword_id = _build_fixture(db)
    result = compute_keyword_opportunity(db, keyword_id, page_ours["page_id"])
    assert result["entity_type"] == "keyword"
    assert result["query"] == QUERY
    assert result["keyword_opportunity_score"] is not None
    assert result["our_rank"] == 15
    assert result["aio_competitors_cited"] == 1  # only competitor B cited
    assert result["ai_mode_competitors_cited"] == 1


def test_get_opportunity_returns_none_before_compute(db):
    page_a, page_b, page_ours, _ = _build_fixture(db)
    assert get_opportunity(db, "page", page_ours["page_id"]) is None
    compute_page_opportunity(db, page_ours["page_id"], [page_a["page_id"]])
    assert get_opportunity(db, "page", page_ours["page_id"]) is not None


def test_compute_page_opportunity_is_idempotent_upsert(db):
    page_a, page_b, page_ours, _ = _build_fixture(db)
    first = compute_page_opportunity(db, page_ours["page_id"], [page_a["page_id"]])
    second = compute_page_opportunity(db, page_ours["page_id"], [page_a["page_id"]])
    assert first["opportunity_id"] == second["opportunity_id"]
    rows = db.query("SELECT COUNT(*) AS n FROM ci_opportunity_analyses WHERE entity_id=?", (page_ours["page_id"],))
    assert rows[0]["n"] == 1


def test_content_gaps_stored_per_competitor(db):
    page_a, page_b, page_ours, _ = _build_fixture(db)
    compute_page_opportunity(db, page_ours["page_id"], [page_a["page_id"], page_b["page_id"]])
    from db_collector_os.competitive_intelligence.opportunity.repository import ContentGapRepository
    gaps = ContentGapRepository(db).list_for_our_page(page_ours["page_id"])
    assert len(gaps) == 2
    competitor_ids = {g["competitor_page_id"] for g in gaps}
    assert competitor_ids == {page_a["page_id"], page_b["page_id"]}


def test_compare_pages_stores_all_dimensions(db):
    page_a, page_b, page_ours, _ = _build_fixture(db)
    from db_collector_os.competitive_intelligence.opportunity.comparison import DIMENSIONS
    results = compare_pages(db, page_ours["page_id"], page_a["page_id"])
    assert {r["comparison_dimension"] for r in results} == set(DIMENSIONS)


def test_compare_pages_organic_rank_winner_is_competitor(db):
    page_a, page_b, page_ours, _ = _build_fixture(db)
    results = compare_pages(db, page_ours["page_id"], page_a["page_id"])
    organic = next(r for r in results if r["comparison_dimension"] == "organic_rank")
    assert organic["winner"] == "right"  # competitor A ranks 1, we rank 15


def test_compare_pages_readiness_winner_is_our_page(db):
    page_a, page_b, page_ours, _ = _build_fixture(db)
    results = compare_pages(db, page_ours["page_id"], page_a["page_id"])
    readiness = next(r for r in results if r["comparison_dimension"] == "readiness")
    assert readiness["winner"] == "left"


def test_compare_pages_unknown_page_raises(db):
    import pytest
    page_a, page_b, page_ours, _ = _build_fixture(db)
    with pytest.raises(ValueError):
        compare_pages(db, page_ours["page_id"], "no-such-page")


def test_compare_domains(db):
    page_a, page_b, page_ours, _ = _build_fixture(db)
    results = compare_domains(db, page_ours["domain_id"], page_a["domain_id"])
    assert len(results) > 0
    assert all("comparison_id" in r for r in results)


def test_compare_keywords(db):
    page_a, page_b, page_ours, keyword_id = _build_fixture(db)
    other_keyword_id = _ensure_primary_keyword(db, page_a["page_id"], page_a["crawl_run_id"], "別のキーワード", commercial_score=10)
    results = compare_keywords(db, keyword_id, other_keyword_id)
    assert len(results) > 0


def test_recompute_all(db):
    """Competitor A's page is deliberately thin (spec section 30's
    "organic-strong-only" competitor) and correctly fails PHASE 1's own
    `analysis_target` classification threshold -- `recompute_all` only
    bulk-processes real analysis targets, so it legitimately covers our
    page and Competitor B (both substantive) but not Competitor A."""
    page_a, page_b, page_ours, keyword_id = _build_fixture(db)
    summary = recompute_all(db)
    assert summary["pages_computed"] >= 2
    assert summary["keywords_computed"] >= 1
    assert get_opportunity(db, "page", page_ours["page_id"]) is not None
    assert get_opportunity(db, "page", page_b["page_id"]) is not None


def test_recompute_all_scoped_to_one_crawl_run(db):
    page_a, page_b, page_ours, _ = _build_fixture(db)
    summary = recompute_all(db, crawl_run_id=page_ours["crawl_run_id"])
    assert summary["pages_computed"] == 1
    assert get_opportunity(db, "page", page_ours["page_id"]) is not None
    assert get_opportunity(db, "page", page_a["page_id"]) is None
