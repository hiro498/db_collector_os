from __future__ import annotations

import json

import responses

from db_collector_os.competitive_intelligence.ai_search import analyze_ai_page
from db_collector_os.competitive_intelligence.ai_search.observation.importer import import_observation_file
from db_collector_os.competitive_intelligence.ai_search.observation.pipeline import recompute_page_visibility
from db_collector_os.competitive_intelligence.ai_search.observation.repository import ImportBatchRepository
from db_collector_os.competitive_intelligence.ai_search.repository import AiFanoutQueryRepository
from db_collector_os.competitive_intelligence.crawler import CrawlEngine
from db_collector_os.competitive_intelligence.repository.pages import PageRepository

_HTML = """<!doctype html><html><head><title>t</title>
<link rel="canonical" href="https://example.jp/ramen/"></head><body>
<main><h1>渋谷のラーメンおすすめランキング</h1><p>編集部が実際に42店舗を食べ比べました。</p></main>
</body></html>"""


def _crawl(db):
    with responses.RequestsMock() as rsps:
        rsps.add(responses.GET, "https://example.jp/ramen/", body=_HTML, content_type="text/html")
        engine = CrawlEngine(db, user_agent="TestBot/1.0")
        run_id = engine.start_advertiser_lp("https://example.jp/ramen/", requested_mode="advertiser_lp")
    return PageRepository(db).list_for_run(run_id, limit=1)[0]


def test_import_unknown_observation_type_raises(db, tmp_path):
    import pytest
    f = tmp_path / "x.json"
    f.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError):
        import_observation_file(db, str(f), "not_a_real_type")


def test_import_missing_file_raises(db, tmp_path):
    import pytest
    with pytest.raises(FileNotFoundError):
        import_observation_file(db, str(tmp_path / "missing.json"), "organic")


def test_import_unsupported_extension_raises(db, tmp_path):
    import pytest
    f = tmp_path / "x.txt"
    f.write_text("data", encoding="utf-8")
    with pytest.raises(ValueError):
        import_observation_file(db, str(f), "organic")


def test_import_organic_json(db, tmp_path):
    page = _crawl(db)
    f = tmp_path / "organic.json"
    f.write_text(json.dumps([
        {"query": "q", "country": "JP", "language": "ja", "device": "desktop", "observed_at": "2026-01-01T00:00:00Z",
         "provider": "manual", "results": [{"result_position": 1, "result_url": page["url"]}]},
    ]), encoding="utf-8")
    result = import_observation_file(db, str(f), "organic", provider="manual")
    assert result["status"] == "imported"
    assert result["imported"] == 1
    assert result["errors"] == 0


def test_import_same_file_twice_is_already_imported(db, tmp_path):
    page = _crawl(db)
    f = tmp_path / "organic.json"
    f.write_text(json.dumps([
        {"query": "q", "country": "JP", "language": "ja", "device": "desktop", "observed_at": "2026-01-01T00:00:00Z",
         "provider": "manual", "results": [{"result_position": 1, "result_url": page["url"]}]},
    ]), encoding="utf-8")
    first = import_observation_file(db, str(f), "organic", provider="manual")
    second = import_observation_file(db, str(f), "organic", provider="manual")
    assert first["status"] == "imported"
    assert second["status"] == "already_imported"
    assert len(ImportBatchRepository(db).list_recent()) == 1


def test_import_duplicate_record_within_type_is_skipped_not_errored(db, tmp_path):
    page = _crawl(db)
    f = tmp_path / "organic.json"
    same_record = {"query": "q", "country": "JP", "language": "ja", "device": "desktop",
                    "observed_at": "2026-01-01T00:00:00Z", "provider": "manual",
                    "results": [{"result_position": 1, "result_url": page["url"]}]}
    f.write_text(json.dumps([same_record, same_record]), encoding="utf-8")
    result = import_observation_file(db, str(f), "organic", provider="manual")
    assert result["imported"] == 1
    assert result["skipped_duplicate"] == 1
    assert result["errors"] == 0


def test_import_malformed_record_counts_as_error_not_crash(db, tmp_path):
    page = _crawl(db)
    f = tmp_path / "organic.json"
    f.write_text(json.dumps([
        {"query": "q", "results": [{"result_position": 1, "result_url": page["url"]}]},  # missing observed_at/provider
    ]), encoding="utf-8")
    result = import_observation_file(db, str(f), "organic", provider="manual")
    assert result["status"] == "imported"
    assert result["imported"] == 0
    assert result["errors"] == 1


def test_import_aio_json_with_citations(db, tmp_path):
    page = _crawl(db)
    f = tmp_path / "aio.json"
    f.write_text(json.dumps([
        {"query": "q", "country": "JP", "language": "ja", "device": "desktop", "observed_at": "2026-01-01T00:00:00Z",
         "provider": "manual", "aio_present": True,
         "citations": [{"citation_position": 1, "citation_url": page["url"]}]},
    ]), encoding="utf-8")
    result = import_observation_file(db, str(f), "aio", provider="manual")
    assert result["imported"] == 1


def test_import_organic_csv_flat_rows_group_into_one_observation(db, tmp_path):
    page = _crawl(db)
    csv_path = tmp_path / "organic.csv"
    csv_path.write_text(
        "query,country,language,device,observed_at,provider,status,result_position,result_url\n"
        f"q,JP,ja,desktop,2026-01-01T00:00:00Z,manual_csv,available,1,{page['url']}\n"
        f"q,JP,ja,desktop,2026-01-01T00:00:00Z,manual_csv,available,2,https://competitor.example/\n",
        encoding="utf-8",
    )
    result = import_observation_file(db, str(csv_path), "organic", provider="manual_csv")
    assert result["imported"] == 1  # two rows, same observation key -> one observation

    from db_collector_os.competitive_intelligence.ai_search.observation.repository import SerpObservationRepository
    obs = SerpObservationRepository(db).latest_for_query("q", "JP", "ja", "desktop")
    results = SerpObservationRepository(db).results_for_observation(obs["serp_observation_id"])
    assert len(results) == 2


def test_import_fanout_resolves_fanout_query_id_by_page_and_text(db, tmp_path):
    page = _crawl(db)
    analyze_ai_page(db, page["page_id"])
    fq = AiFanoutQueryRepository(db).list_for_page(page["page_id"])[0]
    f = tmp_path / "fanout.json"
    f.write_text(json.dumps([
        {"parent_query": fq["base_keyword"], "fanout_query": fq["subquery_text"], "fanout_intent": fq["intent_class"],
         "country": "JP", "language": "ja", "device": "desktop", "observed_at": "2026-01-01T00:00:00Z",
         "provider": "manual", "target_page_id": page["page_id"], "target_rank": 4, "target_cited": True,
         "result_urls": [page["url"]]},
    ]), encoding="utf-8")
    result = import_observation_file(db, str(f), "fanout", provider="manual")
    assert result["imported"] == 1
    assert result["errors"] == 0

    visibility = recompute_page_visibility(db, page["page_id"])
    assert visibility["fanout_queries_observed"] == 1
    assert visibility["fanout_citation_count"] == 1


def test_import_fanout_unresolvable_query_is_an_error(db, tmp_path):
    f = tmp_path / "fanout.json"
    f.write_text(json.dumps([
        {"parent_query": "kw", "fanout_query": "no such subquery text", "country": "JP", "language": "ja",
         "device": "desktop", "observed_at": "2026-01-01T00:00:00Z", "provider": "manual",
         "target_page_id": "no-such-page"},
    ]), encoding="utf-8")
    result = import_observation_file(db, str(f), "fanout", provider="manual")
    assert result["imported"] == 0
    assert result["errors"] == 1


def test_import_gsc_json(db, tmp_path):
    f = tmp_path / "gsc.json"
    f.write_text(json.dumps([
        {"gsc_query": "q", "gsc_page": "https://example.jp/ramen/", "observed_date": "2026-01-01",
         "impressions": 100, "clicks": 10, "ctr": 0.1, "position": 5.2},
    ]), encoding="utf-8")
    result = import_observation_file(db, str(f), "gsc", provider="manual_export")
    assert result["imported"] == 1

    from db_collector_os.competitive_intelligence.ai_search.observation.repository import GscObservationRepository
    rows = GscObservationRepository(db).list_for_page("https://example.jp/ramen")
    assert len(rows) == 1
    assert rows[0]["clicks"] == 10
