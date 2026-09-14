from __future__ import annotations

import json

import responses
from fastapi.testclient import TestClient

from db_collector_os.competitive_intelligence import service
from db_collector_os.competitive_intelligence.crawler import CrawlEngine
from db_collector_os.competitive_intelligence.repository.pages import PageRepository
from db_collector_os.competitive_intelligence.web.app import create_ci_app

_HTML = """<!doctype html><html><head><title>t</title>
<link rel="canonical" href="https://example.jp/ramen/"></head><body>
<main><h1>渋谷のラーメンおすすめランキング</h1><p>編集部が実際に42店舗を食べ比べました。</p></main>
</body></html>"""


def _crawl_and_analyze(config):
    db_config = config
    from db_collector_os.database import Database
    db = Database(db_config.db_path)
    with responses.RequestsMock() as rsps:
        rsps.add(responses.GET, "https://example.jp/ramen/", body=_HTML, content_type="text/html")
        engine = CrawlEngine(db, user_agent="TestBot/1.0")
        run_id = engine.start_advertiser_lp("https://example.jp/ramen/", requested_mode="advertiser_lp")
    page = PageRepository(db).list_for_run(run_id, limit=1)[0]
    db.close()
    service.analyze_ai_page(config, page["page_id"])
    return run_id, page["page_id"]


def test_page_detail_shows_not_yet_executed_before_recompute(app_config):
    run_id, page_id = _crawl_and_analyze(app_config)
    app = create_ci_app(app_config)
    client = TestClient(app)
    r = client.get(f"/runs/{run_id}/pages/{page_id}")
    assert r.status_code == 200
    assert "まだ外部観測ロールアップを実行していません" in r.text
    assert "Organic Rank" not in r.text


def test_visibility_recompute_route_and_rendering(app_config, tmp_path):
    run_id, page_id = _crawl_and_analyze(app_config)

    organic_file = tmp_path / "organic.json"
    organic_file.write_text(json.dumps([
        {"query": "渋谷 ラーメン", "country": "JP", "language": "ja", "device": "desktop",
         "observed_at": "2026-01-01T00:00:00Z", "provider": "manual",
         "results": [{"result_position": 6, "result_url": "https://example.jp/ramen/"}]},
    ]), encoding="utf-8")
    result = service.import_observation(app_config, str(organic_file), "organic", provider="manual")
    assert result["status"] == "imported"

    app = create_ci_app(app_config)
    client = TestClient(app)
    post_result = client.post(f"/runs/{run_id}/pages/{page_id}/visibility-recompute", follow_redirects=False)
    assert post_result.status_code == 303

    r = client.get(f"/runs/{run_id}/pages/{page_id}")
    assert r.status_code == 200
    assert "Organic Rank" in r.text
    assert ">6<" in r.text
    # AIO/AI Mode were never observed -- their table cells must render as
    # "Not Observed", never a bare 0. The static explanatory paragraph
    # (which itself says '...0や未引用と混同されることはありません') is expected
    # and is not one of those cells.
    assert r.text.count("未引用") == 1
    assert "<td>Not Observed</td>" in r.text


def test_page_detail_404_for_wrong_run_id(app_config):
    run_id, page_id = _crawl_and_analyze(app_config)
    app = create_ci_app(app_config)
    client = TestClient(app)
    r = client.get(f"/runs/wrong-run-id/pages/{page_id}")
    assert r.status_code == 404
