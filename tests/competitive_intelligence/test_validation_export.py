from __future__ import annotations

import csv
import json

import responses

from db_collector_os.competitive_intelligence.validation import ValidationOptions, run_validation
from db_collector_os.competitive_intelligence.validation.exporter import export_all
from db_collector_os.competitive_intelligence.validation.repository import ValidationRunRepository

from .fixtures.affiliate_site import BASE, build_fixture_site


def _run_fixture_validation(db) -> str:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        pages = build_fixture_site()
        rsps.add(responses.GET, f"{BASE}/robots.txt", status=404)
        rsps.add(responses.GET, f"{BASE}/sitemap.xml", status=404)
        for url, html in pages.items():
            rsps.add(responses.GET, url, body=html, content_type="text/html")
        return run_validation(db, f"{BASE}/", ValidationOptions(max_pages=30, rate_limit_requests_per_second=100_000.0))


def test_export_all_creates_nine_files(db, tmp_path):
    validation_run_id = _run_fixture_validation(db)
    paths = export_all(db, validation_run_id, str(tmp_path))
    assert len(paths) == 9
    for p in paths:
        assert __import__("pathlib").Path(p).exists()


def test_export_unknown_run_raises(db, tmp_path):
    import pytest
    with pytest.raises(ValueError):
        export_all(db, "no-such-run", str(tmp_path))


def test_target_keywords_csv_encoding_and_columns(db, tmp_path):
    validation_run_id = _run_fixture_validation(db)
    export_all(db, validation_run_id, str(tmp_path))
    path = tmp_path / "target_keywords.csv"
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    header = rows[0]
    for col in ("rank", "keyword", "normalized_keyword", "intent", "commercial_score", "money_keyword_class",
                "competitor_page_count", "best_competitor_page", "keyword_score", "ai_readiness", "organic_rank",
                "aio_cited", "ai_mode_cited", "content_gap_score", "opportunity_score", "confidence", "top_reason",
                "recommended_action", "demand_status"):
        assert col in header
    assert len(rows) > 1


def test_summary_json_matches_stored_run(db, tmp_path):
    validation_run_id = _run_fixture_validation(db)
    export_all(db, validation_run_id, str(tmp_path))
    summary_file = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    run = ValidationRunRepository(db).get(validation_run_id)
    stored_summary = json.loads(run["summary_json"])
    assert summary_file["target_domain"] == stored_summary["target_domain"]
    assert summary_file["production_validation_status"] == stored_summary["production_validation_status"]


def test_noise_audit_csv_contains_only_noise_rows(db, tmp_path):
    validation_run_id = _run_fixture_validation(db)
    export_all(db, validation_run_id, str(tmp_path))
    with open(tmp_path / "noise_audit.csv", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) > 0
    for row in rows:
        assert row["noise_reason"]


def test_content_map_csv_has_expected_columns(db, tmp_path):
    validation_run_id = _run_fixture_validation(db)
    export_all(db, validation_run_id, str(tmp_path))
    with open(tmp_path / "content_map.csv", encoding="utf-8-sig", newline="") as f:
        header = next(csv.reader(f))
    for col in ("topic", "keyword_count", "page_count", "article_count", "category_count", "ranking_count",
                "comparison_count", "commercial_keyword_count"):
        assert col in header
