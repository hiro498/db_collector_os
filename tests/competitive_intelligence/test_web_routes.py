from __future__ import annotations

import responses
from fastapi.testclient import TestClient

from db_collector_os.competitive_intelligence.crawler import CrawlEngine
from db_collector_os.competitive_intelligence.web.app import create_ci_app

_HTML = """<!doctype html><html><head><title>渋谷ラーメンおすすめランキング</title>
<link rel="canonical" href="https://example.jp/ramen/"></head><body>
<main><h1>渋谷ラーメンおすすめランキング</h1><p>渋谷のラーメン店を紹介します。</p></main>
</body></html>"""


@responses.activate
def _build_run(db):
    responses.add(responses.GET, "https://example.jp/ramen/", body=_HTML, content_type="text/html")
    engine = CrawlEngine(db, user_agent="TestBot/1.0")
    return engine.start_advertiser_lp("https://example.jp/ramen/", requested_mode="advertiser_lp")


def test_top_and_new_pages_render(app_config, db):
    _build_run(db)
    client = TestClient(create_ci_app(app_config))
    assert client.get("/").status_code == 200
    assert client.get("/new").status_code == 200


def test_pages_view_includes_link_metrics_from_link_analyzer(app_config, db):
    # Guards against link_analyzer.compute_link_metrics being orphaned
    # code that's never actually called from the dashboard.
    run_id = _build_run(db)
    client = TestClient(create_ci_app(app_config))
    resp = client.get(f"/runs/{run_id}/pages")
    assert resp.status_code == 200
    assert "In/Out Links" in resp.text
    assert "TOP距離" in resp.text


def test_run_status_audit_pages_keywords_render(app_config, db):
    run_id = _build_run(db)
    client = TestClient(create_ci_app(app_config))
    for path in (f"/runs/{run_id}", f"/runs/{run_id}/audit", f"/runs/{run_id}/pages", f"/runs/{run_id}/keywords"):
        resp = client.get(path)
        assert resp.status_code == 200, (path, resp.text[:500])


def test_unknown_run_returns_404(app_config, db):
    client = TestClient(create_ci_app(app_config))
    assert client.get("/runs/does-not-exist").status_code == 404


def test_keyword_detail_page_renders(app_config, db):
    run_id = _build_run(db)
    keyword = db.query_one("SELECT keyword_id FROM ci_keywords LIMIT 1")
    client = TestClient(create_ci_app(app_config))
    resp = client.get(f"/runs/{run_id}/keywords/{keyword['keyword_id']}")
    assert resp.status_code == 200


def test_export_route_returns_csv(app_config, db):
    run_id = _build_run(db)
    client = TestClient(create_ci_app(app_config))
    resp = client.get(f"/runs/{run_id}/export?file=keywords.csv")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")


def test_export_route_rejects_arbitrary_file_names(app_config, db):
    run_id = _build_run(db)
    client = TestClient(create_ci_app(app_config))
    resp = client.get(f"/runs/{run_id}/export?file=../../etc/passwd", follow_redirects=False)
    assert resp.status_code in (303, 307)  # falls back to redirect, never serves an arbitrary path


def test_new_investigation_post_starts_a_run_and_redirects(app_config, db):
    with responses.RequestsMock() as rsps:
        rsps.add(responses.GET, "https://example.jp/ramen2/", body=_HTML, content_type="text/html")
        client = TestClient(create_ci_app(app_config))
        resp = client.post(
            "/new", data={"url": "https://example.jp/ramen2/", "mode": "advertiser_lp"}, follow_redirects=False,
        )
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/runs/")


def test_resume_reanalyze_recompute_actions_do_not_error(app_config, db):
    run_id = _build_run(db)
    client = TestClient(create_ci_app(app_config))
    assert client.post(f"/runs/{run_id}/reanalyze", follow_redirects=False).status_code == 303
    assert client.post(f"/runs/{run_id}/recompute-keywords", follow_redirects=False).status_code == 303
    assert client.post(f"/runs/{run_id}/stop", follow_redirects=False).status_code == 303
