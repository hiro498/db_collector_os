from __future__ import annotations

import os

import pytest

from db_collector_os.viability.keyword_sources.base import NotConfiguredError, NullKeywordSource
from db_collector_os.viability.keyword_sources.csv_import import CsvKeywordSource
from db_collector_os.viability.keyword_sources.keyword_planner import KeywordPlannerSource
from db_collector_os.viability.keyword_sources.rakko import RakkoKeywordSource


def test_null_keyword_source_returns_nothing():
    assert NullKeywordSource().fetch(["anything"]) == []


def test_csv_keyword_source_parses_rows(tmp_path):
    csv_path = tmp_path / "kw.csv"
    csv_path.write_text(
        "keyword,monthly_search_volume,competition,low_bid,high_bid,trend\n"
        "アクセサリー オーダーメイド,880,0.3,50,120,up\n"
        "指輪 オーダーメイド,,,,, \n",
        encoding="utf-8",
    )
    records = CsvKeywordSource(csv_path).fetch()
    assert len(records) == 2
    first = records[0]
    assert first.keyword == "アクセサリー オーダーメイド"
    assert first.monthly_search_volume == 880
    assert first.source == "csv_import"
    assert first.competition == 0.3
    assert first.trend == "up"
    # blank volume -> None, not 0 or a crash
    assert records[1].monthly_search_volume is None


def test_csv_keyword_source_filters_by_requested_keywords(tmp_path):
    csv_path = tmp_path / "kw.csv"
    csv_path.write_text(
        "keyword,monthly_search_volume\nA,1\nB,2\nC,3\n", encoding="utf-8"
    )
    records = CsvKeywordSource(csv_path).fetch(["A", "C"])
    assert {r.keyword for r in records} == {"A", "C"}


def test_csv_keyword_source_respects_explicit_source_column(tmp_path):
    csv_path = tmp_path / "kw.csv"
    csv_path.write_text("keyword,monthly_search_volume,source\nA,1,rakko\n", encoding="utf-8")
    records = CsvKeywordSource(csv_path).fetch()
    assert records[0].source == "rakko"


def test_keyword_planner_fails_closed_without_credentials(monkeypatch):
    for var in (
        "GOOGLE_ADS_DEVELOPER_TOKEN", "GOOGLE_ADS_CLIENT_ID", "GOOGLE_ADS_CLIENT_SECRET",
        "GOOGLE_ADS_REFRESH_TOKEN", "GOOGLE_ADS_LOGIN_CUSTOMER_ID",
    ):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(NotConfiguredError):
        KeywordPlannerSource()


def test_rakko_source_always_directs_to_csv_import():
    with pytest.raises(NotConfiguredError):
        RakkoKeywordSource()
