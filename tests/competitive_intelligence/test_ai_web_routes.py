from __future__ import annotations

import responses
from fastapi.testclient import TestClient

from db_collector_os.competitive_intelligence.crawler import CrawlEngine
from db_collector_os.competitive_intelligence.repository.pages import PageRepository
from db_collector_os.competitive_intelligence.web.app import create_ci_app

_HTML = """<!doctype html><html><head><title>渋谷ラーメンおすすめランキング</title>
<link rel="canonical" href="https://example.jp/ramen/"></head><body>
<main><h1>渋谷ラーメンおすすめランキング</h1><p>編集部が実際に調査した結果、同ジャンル100件中上位5%です。</p></main>
</body></html>"""


@responses.activate
def _seed_page(db):
    responses.add(responses.GET, "https://example.jp/ramen/", body=_HTML, content_type="text/html")
    engine = CrawlEngine(db, user_agent="TestBot/1.0")
    run_id = engine.start_advertiser_lp("https://example.jp/ramen/", requested_mode="advertiser_lp")
    page = PageRepository(db).list_for_run(run_id, limit=1)[0]
    return run_id, page["page_id"]


def test_page_detail_route_renders_before_ai_analysis(app_config, db):
    run_id, page_id = _seed_page(db)
    client = TestClient(create_ci_app(app_config))
    resp = client.get(f"/runs/{run_id}/pages/{page_id}")
    assert resp.status_code == 200
    assert "AI Search Analysis" in resp.text


def test_ai_analyze_action_then_page_detail_shows_scores(app_config, db):
    run_id, page_id = _seed_page(db)
    client = TestClient(create_ci_app(app_config))
    resp = client.post(f"/runs/{run_id}/pages/{page_id}/ai-analyze", follow_redirects=False)
    assert resp.status_code == 303

    resp = client.get(f"/runs/{run_id}/pages/{page_id}")
    assert resp.status_code == 200
    assert "AI Citation Readiness Score" in resp.text


def test_unavailable_external_axes_render_as_text_not_zero(app_config, db):
    run_id, page_id = _seed_page(db)
    client = TestClient(create_ci_app(app_config))
    client.post(f"/runs/{run_id}/pages/{page_id}/ai-analyze")
    resp = client.get(f"/runs/{run_id}/pages/{page_id}")
    assert "External observation required" in resp.text
    assert "Unavailable" in resp.text or "Not observed" in resp.text


def test_ai_recompute_action_succeeds(app_config, db):
    run_id, page_id = _seed_page(db)
    client = TestClient(create_ci_app(app_config))
    client.post(f"/runs/{run_id}/pages/{page_id}/ai-analyze")
    resp = client.post(f"/runs/{run_id}/pages/{page_id}/ai-recompute", follow_redirects=False)
    assert resp.status_code == 303


def test_pages_list_links_to_page_detail(app_config, db):
    run_id, page_id = _seed_page(db)
    client = TestClient(create_ci_app(app_config))
    resp = client.get(f"/runs/{run_id}/pages")
    assert resp.status_code == 200
    assert f"/runs/{run_id}/pages/{page_id}" in resp.text


def test_page_detail_unknown_page_returns_404(app_config, db):
    run_id, _page_id = _seed_page(db)
    client = TestClient(create_ci_app(app_config))
    resp = client.get(f"/runs/{run_id}/pages/does-not-exist")
    assert resp.status_code == 404


def test_evidence_tables_render_in_page_detail(app_config, db):
    run_id, page_id = _seed_page(db)
    client = TestClient(create_ci_app(app_config))
    client.post(f"/runs/{run_id}/pages/{page_id}/ai-analyze")
    resp = client.get(f"/runs/{run_id}/pages/{page_id}")
    assert "Numeric Facts" in resp.text
    assert "Comparison" in resp.text
    assert "Fan-out" in resp.text
