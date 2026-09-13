from __future__ import annotations

import csv

import responses

from db_collector_os.competitive_intelligence.crawler import CrawlEngine
from db_collector_os.competitive_intelligence.exporter import export_all

_HTML = """<!doctype html><html><head><title>渋谷ラーメンおすすめランキング</title>
<link rel="canonical" href="https://example.jp/ramen/"></head><body>
<main><h1>渋谷ラーメンおすすめランキング</h1><p>渋谷のラーメン店を紹介します。</p></main>
</body></html>"""


def _build_run(db):
    with responses.RequestsMock() as rsps:
        rsps.add(responses.GET, "https://example.jp/ramen/", body=_HTML, content_type="text/html")
        engine = CrawlEngine(db, user_agent="TestBot/1.0")
        return engine.start_advertiser_lp("https://example.jp/ramen/", requested_mode="advertiser_lp")


def test_export_all_produces_five_csv_files_with_expected_headers(db, tmp_path):
    run_id = _build_run(db)
    paths = export_all(db, run_id, str(tmp_path))
    names = {p.split("/")[-1] for p in paths}
    assert names == {"domain_summary.csv", "pages.csv", "keywords.csv", "page_keywords.csv", "crawl_audit.csv"}

    for path in paths:
        with open(path, encoding="utf-8-sig") as fh:
            rows = list(csv.reader(fh))
        assert len(rows) >= 1  # header row always present

    keywords_path = next(p for p in paths if p.endswith("keywords.csv"))
    with open(keywords_path, encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        header = reader.fieldnames
        rows = list(reader)
    assert header == [
        "domain", "keyword", "normalized_keyword", "score", "importance", "intent", "intent_group",
        "commercial_score", "branded_type", "modifier", "local", "prefecture", "city", "keyword_class",
        "page_count", "primary_page_count", "cluster",
    ]
    assert len(rows) > 0
    assert any(r["keyword"] == "ラーメン" for r in rows)

    page_keywords_path = next(p for p in paths if p.endswith("page_keywords.csv"))
    with open(page_keywords_path, encoding="utf-8-sig") as fh:
        header = csv.DictReader(fh).fieldnames
    assert header == [
        "domain", "url", "title", "page_type", "keyword", "score", "importance", "intent",
        "commercial_score", "title_hit", "h1_hit", "h2_count", "body_count", "anchor_count", "rule_boost",
    ]


def test_export_domain_summary_reflects_run_counters(db, tmp_path):
    run_id = _build_run(db)
    paths = export_all(db, run_id, str(tmp_path))
    summary_path = next(p for p in paths if p.endswith("domain_summary.csv"))
    with open(summary_path, encoding="utf-8-sig") as fh:
        row = next(csv.DictReader(fh))
    assert row["domain"] == "example.jp"
    assert row["status"] == "completed"
    assert int(row["discovered_total"]) >= 1
