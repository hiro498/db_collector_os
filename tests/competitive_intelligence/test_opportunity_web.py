from __future__ import annotations

import responses
from fastapi.testclient import TestClient

from db_collector_os.database import Database
from db_collector_os.competitive_intelligence import service
from db_collector_os.competitive_intelligence.crawler import CrawlEngine
from db_collector_os.competitive_intelligence.repository.pages import PageRepository
from db_collector_os.competitive_intelligence.web.app import create_ci_app

_HTML_A = """<!doctype html><html><head><title>おすすめ 睡眠グッズまとめ</title>
<link rel="canonical" href="https://competitor-a.example/page/"></head><body>
<main><h1>おすすめ 睡眠グッズまとめ</h1><p>おすすめ 睡眠グッズについて簡単に紹介します。</p></main>
</body></html>"""

_HTML_OURS = """<!doctype html><html><head><title>おすすめ 睡眠グッズ【2026年最新・独自調査】</title>
<link rel="canonical" href="https://our-site.example/page/"></head><body>
<main><h1>おすすめ 睡眠グッズ【2026年最新版・独自調査】</h1>
<p>編集部が実際に80点を試し、独自調査・n=80のアンケート調査を実施した結果をもとに作成しました。
同ジャンル1,000点中上位1%です。レビュー数は300件から900件に増加しました。順位も25位から2位に上昇しています。
調査方法は覆面調査です。サンプルサイズはn=80です。価格帯・特徴も含めて徹底的に比較しています。</p>
<table><tr><th>商品</th><th>評価</th></tr><tr><td>A</td><td>4.8</td></tr></table>
</main></body></html>"""


def _crawl_and_analyze(config, html, url):
    db = Database(config.db_path)
    with responses.RequestsMock() as rsps:
        rsps.add(responses.GET, url, body=html, content_type="text/html")
        engine = CrawlEngine(db, user_agent="TestBot/1.0")
        run_id = engine.start_advertiser_lp(url, requested_mode="advertiser_lp")
    page = PageRepository(db).list_for_run(run_id, limit=1)[0]
    db.close()
    service.analyze_ai_page(config, page["page_id"])
    return page["page_id"]


def test_opportunities_list_empty(app_config):
    app = create_ci_app(app_config)
    client = TestClient(app)
    r = client.get("/opportunities")
    assert r.status_code == 200
    assert "Opportunities" in r.text


def test_opportunity_detail_and_compare_routes(app_config):
    page_a = _crawl_and_analyze(app_config, _HTML_A, "https://competitor-a.example/page/")
    page_ours = _crawl_and_analyze(app_config, _HTML_OURS, "https://our-site.example/page/")

    result = service.compute_page_opportunity(app_config, page_ours, [page_a])
    opportunity_id = result["opportunity_id"]

    app = create_ci_app(app_config)
    client = TestClient(app)

    r1 = client.get("/opportunities")
    assert r1.status_code == 200
    assert opportunity_id in r1.text

    r2 = client.get(f"/opportunities/{opportunity_id}")
    assert r2.status_code == 200
    assert "Overall Opportunity" in r2.text
    assert "Not Observed" in r2.text  # demand_score is unavailable (no keyword_metrics import)

    r3 = client.get(f"/opportunities/compare?a={page_ours}&b={page_a}")
    assert r3.status_code == 200
    assert "organic_rank" in r3.text


def test_opportunity_detail_unknown_id_is_404(app_config):
    app = create_ci_app(app_config)
    client = TestClient(app)
    r = client.get("/opportunities/no-such-opportunity")
    assert r.status_code == 404


def test_opportunity_compare_route_registered_before_catch_all_detail_route(app_config):
    """Regression guard: /opportunities/compare, /opportunities/export, and
    /opportunities/recompute must never be swallowed by the
    /opportunities/{opportunity_id} catch-all route."""
    page_a = _crawl_and_analyze(app_config, _HTML_A, "https://competitor-a.example/page/")
    page_ours = _crawl_and_analyze(app_config, _HTML_OURS, "https://our-site.example/page/")
    app = create_ci_app(app_config)
    client = TestClient(app)
    r = client.get(f"/opportunities/compare?a={page_ours}&b={page_a}")
    assert r.status_code == 200


def test_opportunity_recompute_route(app_config):
    page_ours = _crawl_and_analyze(app_config, _HTML_OURS, "https://our-site.example/page/")
    app = create_ci_app(app_config)
    client = TestClient(app)
    r = client.post("/opportunities/recompute", follow_redirects=False)
    assert r.status_code == 303
    assert service.get_opportunity(app_config, "page", page_ours) is not None


def test_opportunity_export_route_returns_csv(app_config):
    page_ours = _crawl_and_analyze(app_config, _HTML_OURS, "https://our-site.example/page/")
    service.compute_page_opportunity(app_config, page_ours, [])
    app = create_ci_app(app_config)
    client = TestClient(app)
    r = client.get("/opportunities/export?file=opportunities.csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")


def test_opportunity_export_route_rejects_unknown_file(app_config):
    app = create_ci_app(app_config)
    client = TestClient(app)
    r = client.get("/opportunities/export?file=../../etc/passwd", follow_redirects=False)
    assert r.status_code == 307  # redirected back to /opportunities, never served (matches RedirectResponse's default)
