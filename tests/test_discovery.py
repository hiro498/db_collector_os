from __future__ import annotations

from pathlib import Path

import responses

from db_collector_os.discovery.saturation import SaturationConfig, is_saturated
from db_collector_os.discovery.sitemap import discover_from_sitemap
from db_collector_os.discovery.search_provider import NullSearchProvider, StaticSearchProvider
from db_collector_os.discovery.search_discovery import discover_from_search
from db_collector_os.discovery.prefecture import discover_by_prefecture
from db_collector_os.discovery.url_pattern import discover_by_url_pattern
from db_collector_os.fetching.client import FetchEngine
from db_collector_os.run_history import RunHistoryStore

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@responses.activate
def test_sitemap_discovery_parses_urls():
    xml = (FIXTURES_DIR / "sitemap.xml").read_text(encoding="utf-8")
    responses.add(responses.GET, "https://tires.example.com/sitemap.xml", body=xml, content_type="application/xml")
    engine = FetchEngine(user_agent="TestBot/1.0", respect_robots=False)
    found = discover_from_sitemap(engine, "https://tires.example.com/sitemap.xml")
    assert len(found) == 2
    assert found[0].url == "https://tires.example.com/products/super-tire-x"
    assert found[0].method == "sitemap"


@responses.activate
def test_sitemap_discovery_handles_missing_sitemap_gracefully():
    responses.add(responses.GET, "https://example.com/sitemap.xml", status=404)
    engine = FetchEngine(user_agent="TestBot/1.0", respect_robots=False)
    found = discover_from_sitemap(engine, "https://example.com/sitemap.xml")
    assert found == []


def test_null_search_provider_never_raises():
    provider = NullSearchProvider()
    found = discover_from_search(provider, ["some query"])
    assert found == []


def test_static_search_provider_returns_configured_results():
    provider = StaticSearchProvider({"tires tokyo": ["https://example.com/a", "https://example.com/b"]})
    found = discover_from_search(provider, ["tires tokyo"])
    assert len(found) == 2


def test_prefecture_discovery_expands_47_prefectures():
    found = discover_by_prefecture("https://example.com/area/{pref}/")
    assert len(found) == 47
    assert all("area" in f.url for f in found)


def test_url_pattern_discovery_expands_range():
    found = discover_by_url_pattern("https://example.com/item/{n}", start=1, end=5)
    assert len(found) == 5
    assert found[0].url == "https://example.com/item/1"
    assert found[-1].url == "https://example.com/item/5"


def test_saturation_requires_minimum_runs(db, job_id):
    rh = RunHistoryStore(db)
    saturated, reason = is_saturated(rh, job_id, SaturationConfig(min_runs_before_check=3))
    assert not saturated
    assert "only 0" in reason


def test_saturation_detected_after_low_discovery_streak(db, job_id):
    rh = RunHistoryStore(db)
    for _ in range(5):
        run_id = rh.start(job_id)
        rh.record_discovery_stats(job_id, run_id, discovered_total=100, new_candidates=1, duplicate_candidates=99, accepted=1, rejected=0)
    saturated, reason = is_saturated(rh, job_id, SaturationConfig(window_runs=5, new_rate_threshold=0.05, min_runs_before_check=3))
    assert saturated


def test_not_saturated_while_new_discovery_rate_high(db, job_id):
    rh = RunHistoryStore(db)
    for _ in range(5):
        run_id = rh.start(job_id)
        rh.record_discovery_stats(job_id, run_id, discovered_total=100, new_candidates=50, duplicate_candidates=50, accepted=50, rejected=0)
    saturated, _reason = is_saturated(rh, job_id, SaturationConfig(window_runs=5, new_rate_threshold=0.05, min_runs_before_check=3))
    assert not saturated


def test_zero_discovered_total_is_not_saturated(db, job_id):
    """Regression: discovered_total=0 across every run (discovery never
    actually found anything -- e.g. a listing seed never got fetched) used
    to satisfy the "new-discovery rate <= threshold" saturation check
    trivially (0/0 -> rate 0.0), letting Phase 1 "complete" without any
    real discovery ever having run. Zero activity must never count as
    saturation -- only a real, tapering-off rate does.
    """
    rh = RunHistoryStore(db)
    for _ in range(5):
        run_id = rh.start(job_id)
        rh.record_discovery_stats(job_id, run_id, discovered_total=0, new_candidates=0, duplicate_candidates=0, accepted=0, rejected=0)
    saturated, reason = is_saturated(rh, job_id, SaturationConfig(window_runs=5, new_rate_threshold=0.05, min_runs_before_check=3))
    assert not saturated
    assert "discovered_total is 0" in reason
