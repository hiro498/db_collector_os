from __future__ import annotations

import pytest

from db_collector_os.viability.serp_sources.base import NotConfiguredError, NullSerpSource
from db_collector_os.viability.serp_sources.csv_import import CsvSerpSource
from db_collector_os.viability.serp_sources.serp_api import SerpApiSource


def test_null_serp_source_returns_no_results():
    result = NullSerpSource().search("anything")
    assert result.results == []


def test_csv_serp_source_groups_by_query_and_sorts_by_rank(tmp_path):
    csv_path = tmp_path / "serp.csv"
    csv_path.write_text(
        "query,rank,title,url,snippet\n"
        "kw1,2,second,https://b.example/,snippet b\n"
        "kw1,1,first,https://a.example/,snippet a\n"
        "kw2,1,other,https://c.example/,snippet c\n",
        encoding="utf-8",
    )
    source = CsvSerpSource(csv_path)
    result = source.search("kw1")
    assert [r.rank for r in result.results] == [1, 2]
    assert result.results[0].title == "first"
    assert result.results[0].domain == "a.example"

    assert source.search("kw-missing").results == []
    assert set(source.queries()) == {"kw1", "kw2"}


def test_csv_serp_source_reads_manual_overrides(tmp_path):
    csv_path = tmp_path / "serp.csv"
    csv_path.write_text(
        "query,rank,title,url,site_type,page_type,db_type_page,intent_satisfied\n"
        "kw1,1,t,https://a.example/,major_ec,listing,true,false\n",
        encoding="utf-8",
    )
    result = CsvSerpSource(csv_path).search("kw1")
    r = result.results[0]
    assert r.site_type == "major_ec"
    assert r.page_type == "listing"
    assert r.db_type_page is True
    assert r.intent_satisfied is False


def test_csv_serp_source_max_results_truncates(tmp_path):
    csv_path = tmp_path / "serp.csv"
    rows = "\n".join(f"kw,{i},t{i},https://x{i}.example/" for i in range(1, 6))
    csv_path.write_text("query,rank,title,url\n" + rows + "\n", encoding="utf-8")
    result = CsvSerpSource(csv_path).search("kw", max_results=3)
    assert len(result.results) == 3


def test_serp_api_fails_closed_without_key(monkeypatch):
    monkeypatch.delenv("DB_COLLECTOR_SERP_API_KEY", raising=False)
    with pytest.raises(NotConfiguredError):
        SerpApiSource()
