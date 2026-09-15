from __future__ import annotations

import json

from db_collector_os.competitive_intelligence.opportunity.demand_importer import import_keyword_metrics_file
from db_collector_os.competitive_intelligence.opportunity.repository import KeywordMetricsRepository


def test_import_missing_file_raises(db, tmp_path):
    import pytest
    with pytest.raises(FileNotFoundError):
        import_keyword_metrics_file(db, str(tmp_path / "missing.json"))


def test_import_unsupported_extension_raises(db, tmp_path):
    import pytest
    f = tmp_path / "x.txt"
    f.write_text("data", encoding="utf-8")
    with pytest.raises(ValueError):
        import_keyword_metrics_file(db, str(f))


def test_import_json_basic(db, tmp_path):
    f = tmp_path / "demand.json"
    f.write_text(json.dumps([
        {"query": "q1", "source": "manual", "observed_at": "2026-01-01", "search_volume": 1000, "cpc": 120.5},
    ]), encoding="utf-8")
    result = import_keyword_metrics_file(db, str(f))
    assert result == {"imported": 1, "skipped_duplicate": 0, "errors": 0}
    row = KeywordMetricsRepository(db).latest_for_query("q1")
    assert row["search_volume"] == 1000
    assert row["cpc"] == 120.5


def test_import_json_duplicate_record_is_skipped(db, tmp_path):
    f = tmp_path / "demand.json"
    record = {"query": "q1", "source": "manual", "observed_at": "2026-01-01", "search_volume": 1000}
    f.write_text(json.dumps([record, record]), encoding="utf-8")
    result = import_keyword_metrics_file(db, str(f))
    assert result["imported"] == 1
    assert result["skipped_duplicate"] == 1


def test_import_json_malformed_record_counts_as_error(db, tmp_path):
    f = tmp_path / "demand.json"
    f.write_text(json.dumps([{"query": "q1"}]), encoding="utf-8")  # missing required source/observed_at
    result = import_keyword_metrics_file(db, str(f))
    assert result["imported"] == 0
    assert result["errors"] == 1


def test_import_csv_basic(db, tmp_path):
    f = tmp_path / "demand.csv"
    f.write_text(
        "query,source,observed_at,search_volume,trend\n"
        "睡眠グッズ,manual,2026-01-01,2400,rising\n",
        encoding="utf-8",
    )
    result = import_keyword_metrics_file(db, str(f))
    assert result["imported"] == 1
    row = KeywordMetricsRepository(db).latest_for_query("睡眠グッズ")
    assert row["search_volume"] == 2400
    assert row["trend"] == "rising"


def test_import_never_fabricates_a_volume_for_a_missing_column(db, tmp_path):
    f = tmp_path / "demand.csv"
    f.write_text("query,source,observed_at\nq1,manual,2026-01-01\n", encoding="utf-8")
    import_keyword_metrics_file(db, str(f))
    row = KeywordMetricsRepository(db).latest_for_query("q1")
    assert row["search_volume"] is None
