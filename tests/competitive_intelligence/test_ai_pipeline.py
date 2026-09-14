from __future__ import annotations

import responses

from db_collector_os.competitive_intelligence.ai_search import (
    analyze_ai_page,
    get_ai_analysis,
    recompute_ai_analysis,
)
from db_collector_os.competitive_intelligence.ai_search.repository import (
    AiComparisonRepository,
    AiFanoutQueryRepository,
    AiFreshnessEventRepository,
    AiNumericFactRepository,
)
from db_collector_os.competitive_intelligence.crawler import CrawlEngine
from db_collector_os.competitive_intelligence.repository.pages import PageRepository

_RICH_HTML = """<!doctype html><html><head><title>渋谷ラーメンおすすめランキング【独自調査】</title>
<link rel="canonical" href="https://example.jp/ramen/"></head><body>
<nav><a href="/">Top</a><a href="/company/">会社概要</a></nav>
<header>共通サイトヘッダー Copyright 2024 電話: 0120-000-000</header>
<main>
<h1>渋谷のラーメンおすすめランキング【独自調査】</h1>
<p>編集部が実際に42店舗を食べ比べ、独自調査した結果をもとにランキングを作成しました。
同ジャンル2,843店舗中、レビュー数上位2.1%に入る名店を厳選しています。調査方法はn=42の覆面調査です。
レビュー数は428件から517件に増加しました。順位も18位から7位に上昇しています。</p>
<table><caption>上位3店舗比較</caption>
<tr><th>店名</th><th>評価</th><th>価格帯</th></tr>
<tr><td>ラーメン太郎</td><td>4.5</td><td>800円</td></tr>
<tr><td>ラーメン花子</td><td>4.3</td><td>900円</td></tr>
<tr><td>ラーメン次郎</td><td>4.1</td><td>750円</td></tr>
</table>
</main>
<footer>共通フッター Copyright 2024 全店舗一覧はこちら 0120-999-999</footer>
</body></html>"""

_PLAIN_HTML = """<!doctype html><html><head><title>ページ</title></head><body>
<nav><a href="/">Top</a></nav>
<main><h1>ページ</h1><p>このページは特に情報がありません。</p></main>
<footer>共通フッター Copyright 2024</footer>
</body></html>"""


def _crawl(db, html: str, url: str = "https://example.jp/ramen/"):
    with responses.RequestsMock() as rsps:
        rsps.add(responses.GET, url, body=html, content_type="text/html")
        engine = CrawlEngine(db, user_agent="TestBot/1.0")
        run_id = engine.start_advertiser_lp(url, requested_mode="advertiser_lp")
    return PageRepository(db).list_for_run(run_id, limit=1)[0]


def test_analyze_ai_page_end_to_end_produces_a_readiness_score(db):
    page = _crawl(db, _RICH_HTML)
    result = analyze_ai_page(db, page["page_id"])
    assert 0 <= result["ai_citation_readiness_score"] <= 100
    assert result["proprietary_information_score"] > 0
    assert result["comparison_information_score"] > 0


def test_external_dependent_axes_are_null_not_zero(db):
    page = _crawl(db, _RICH_HTML)
    result = analyze_ai_page(db, page["page_id"])
    for field in ("organic_visibility_score", "aio_citation_score", "ai_mode_citation_score",
                  "fanout_coverage_score", "source_affinity_score", "ai_search_total_score"):
        assert result[field] is None, f"{field} must be NULL, not a guessed value"
    for field in ("aio_cited", "ai_mode_cited", "organic_rank", "citation_observation_count"):
        assert result[field] is None


def test_ai_search_total_score_is_null_even_when_readiness_is_high(db):
    """The combined total must never be silently computed from only the
    locally-available axes -- spec section 3."""
    page = _crawl(db, _RICH_HTML)
    result = analyze_ai_page(db, page["page_id"])
    assert result["ai_citation_readiness_score"] > 0
    assert result["ai_search_total_score"] is None


def test_boilerplate_footer_and_header_never_inflate_scores(db):
    """spec section 16: footer copyright years, phone numbers, and nav
    links must not be scored as proprietary/numeric/comparison signals.
    Both fixtures share the identical nav/header/footer boilerplate; only
    the rich fixture's *main content* should drive a real score gap."""
    rich = analyze_ai_page(db, _crawl(db, _RICH_HTML)["page_id"])
    plain = analyze_ai_page(db, _crawl(db, _PLAIN_HTML, url="https://example.jp/plain/")["page_id"])
    assert rich["proprietary_information_score"] > plain["proprietary_information_score"]
    assert rich["numeric_fact_quality_score"] > plain["numeric_fact_quality_score"]
    assert plain["proprietary_information_score"] == 0


def test_recompute_ai_analysis_matches_analyze_ai_page(db):
    page = _crawl(db, _RICH_HTML)
    first = analyze_ai_page(db, page["page_id"])
    second = recompute_ai_analysis(db, page["page_id"])
    assert first["ai_citation_readiness_score"] == second["ai_citation_readiness_score"]


def test_get_ai_analysis_returns_none_before_analysis(db):
    page = _crawl(db, _RICH_HTML)
    assert get_ai_analysis(db, page["page_id"]) is None
    analyze_ai_page(db, page["page_id"])
    assert get_ai_analysis(db, page["page_id"]) is not None


def test_evidence_rows_are_stored_not_just_the_final_score(db):
    """spec section 15: final scores alone are never enough -- every
    signal must have a queryable evidence row."""
    page = _crawl(db, _RICH_HTML)
    analyze_ai_page(db, page["page_id"])
    facts = AiNumericFactRepository(db).list_for_page(page["page_id"])
    comparisons = AiComparisonRepository(db).list_for_page(page["page_id"])
    freshness_events = AiFreshnessEventRepository(db).list_for_page(page["page_id"])
    fanout_queries = AiFanoutQueryRepository(db).list_for_page(page["page_id"])
    assert len(facts) > 0
    assert len(comparisons) > 0
    assert len(freshness_events) > 0
    assert len(fanout_queries) > 0
    assert all(f["source_text"] for f in facts)
    assert all(f["extractor_version"] for f in facts)
    assert all(c["confidence"] is not None for c in comparisons)


def test_recompute_replaces_evidence_rather_than_duplicating(db):
    page = _crawl(db, _RICH_HTML)
    analyze_ai_page(db, page["page_id"])
    count_first = len(AiNumericFactRepository(db).list_for_page(page["page_id"]))
    recompute_ai_analysis(db, page["page_id"])
    count_second = len(AiNumericFactRepository(db).list_for_page(page["page_id"]))
    assert count_first == count_second


def test_analyze_unknown_page_raises_value_error(db):
    import pytest
    with pytest.raises(ValueError):
        analyze_ai_page(db, "no-such-page")


def test_aio_and_ai_mode_scores_are_independent_fields(db):
    """spec section 9: AIO and AI Mode must never be mixed into one score.
    A page with many subtopics/FAQs (AI Mode-favorable structure) but no
    lead-region answer/summary language (AIO-unfavorable) must be able to
    score high on one axis and low on the other -- proving they are
    computed and stored independently, not derived from each other."""
    html = """<!doctype html><html><head><title>t</title></head><body>
    <main><h1>h1</h1><p>特に結論やまとめの言葉はない、ごく普通の書き出しです。詳細な説明が続きます。</p>
    <h2>見出し1</h2><h2>見出し2</h2><h2>見出し3</h2>
    <dl><dt>Q1？</dt><dd>A1</dd></dl><dl><dt>Q2？</dt><dd>A2</dd></dl>
    </main></body></html>"""
    page = _crawl(db, html, url="https://example.jp/structure-only/")
    result = analyze_ai_page(db, page["page_id"])
    assert result["aio_extractability_score"] == 0
    assert result["ai_mode_content_coverage_score"] > 0
