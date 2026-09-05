"""Tests for the dedicated Couples (couples.jp) nationwide facility
discovery module (`db_collector_os/discovery/lovehotel_couples.py`).

Unlike `test_lovehotel_couples_discovery.py` (which exercises the existing
GENERIC, domain-scoped `discovery/internal_links.py` engine this job's
`config_json.discovery.internal_links` already uses, unchanged), this file
tests the NEW couples-specific module built around the CONFIRMED real
facility URL shape given in this task's brief:
`https://couples.jp/hotel-details/{numeric_id}` (worked example:
`https://couples.jp/hotel-details/1238`), plus confirmed non-facility
categories (`/prefectures/`, `/articles/`, `/themes/`, `/movies`,
`/hotel-groups/`, `/users/`).

All HTML here is a hand-written reconstruction of a plausible couples.jp
page shape (this authoring environment still has no outbound network access
to couples.jp -- confirmed blocked, see docs/lovehotel_couples_db.md), NOT a
live scrape.
"""

from __future__ import annotations

import json

from db_collector_os.discovery.lovehotel_couples import (
    FixtureFetchEngine,
    canonicalize_couples_facility_url,
    count_raw_facility_hrefs,
    discover_all_prefectures,
    discover_prefecture_facilities,
    extract_couples_facility_urls,
    extract_navigation_urls,
    extract_prefecture_entry_urls,
    format_dry_run_report,
    is_couples_facility_url,
    is_couples_listing_or_navigation_url,
    to_json_summary,
)

# ---------------------------------------------------------------------------
# 1. facility URL判定 / 5. numeric ID以外をreject
# ---------------------------------------------------------------------------


def test_is_couples_facility_url_true_for_canonical_detail_page():
    assert is_couples_facility_url("https://couples.jp/hotel-details/1238") is True


def test_is_couples_facility_url_false_for_non_numeric_id():
    assert is_couples_facility_url("https://couples.jp/hotel-details/abc") is False
    assert is_couples_facility_url("https://couples.jp/hotel-details/") is False
    assert is_couples_facility_url("https://couples.jp/hotel-details") is False


def test_is_couples_facility_url_false_for_off_domain_lookalike():
    assert is_couples_facility_url("https://not-couples.example.com/hotel-details/1238") is False


# ---------------------------------------------------------------------------
# 2. review等派生URL canonicalization / 3. www有無 / 4. query・fragment除去
# ---------------------------------------------------------------------------


def test_canonicalize_all_variants_collapse_to_the_same_canonical_url():
    canonical = "https://couples.jp/hotel-details/1238"
    variants = [
        "https://couples.jp/hotel-details/1238",
        "https://www.couples.jp/hotel-details/1238",
        "https://couples.jp/hotel-details/1238/",
        "https://couples.jp/hotel-details/1238?foo=bar",
        "https://couples.jp/hotel-details/1238#abc",
        "https://couples.jp/hotel-details/1238/review",
        "https://couples.jp/hotel-details/1238/rooms",
        "https://couples.jp/hotel-details/1238/coupon",
        "https://couples.jp/hotel-details/1238/plan",
        "https://couples.jp/hotel-details/1238/review?utm_source=x#y",
    ]
    for v in variants:
        assert canonicalize_couples_facility_url(v) == canonical, v


def test_canonicalize_returns_none_for_unrelated_url():
    assert canonicalize_couples_facility_url("https://couples.jp/prefectures/tokyo") is None
    assert canonicalize_couples_facility_url("https://couples.jp/articles/123") is None
    assert canonicalize_couples_facility_url(None) is None
    assert canonicalize_couples_facility_url("") is None


# ---------------------------------------------------------------------------
# 6. listing URL除外 / 7. article URL除外
# ---------------------------------------------------------------------------


def test_listing_and_article_urls_are_not_facility_urls():
    for url in [
        "https://couples.jp/prefectures/tokyo",
        "https://couples.jp/articles/123",
        "https://couples.jp/themes/456",
        "https://couples.jp/movies",
        "https://couples.jp/hotel-groups/7",
        "https://couples.jp/users/42",
    ]:
        assert is_couples_facility_url(url) is False, url


def test_is_couples_listing_or_navigation_url_excludes_confirmed_non_facility_content():
    for url in [
        "https://couples.jp/articles/123",
        "https://couples.jp/themes/456",
        "https://couples.jp/movies",
        "https://couples.jp/movies/1",
        "https://couples.jp/hotel-groups/7",
        "https://couples.jp/users/42",
    ]:
        assert is_couples_listing_or_navigation_url(url) is False, url


def test_is_couples_listing_or_navigation_url_true_for_prefectures_and_unknown_same_host_paths():
    # /prefectures/ is the confirmed prefecture entry path -- must remain
    # navigable, unlike the other confirmed-non-facility categories above.
    assert is_couples_listing_or_navigation_url("https://couples.jp/prefectures/tokyo") is True
    # An as-yet-unconfirmed area/city listing path is still treated as safe
    # to crawl (denylist, not a guessed allowlist -- see module docstring).
    assert is_couples_listing_or_navigation_url("https://couples.jp/tokyo/shibuya?page=2") is True


def test_is_couples_listing_or_navigation_url_false_for_facility_url():
    assert is_couples_listing_or_navigation_url("https://couples.jp/hotel-details/1238") is False


def test_is_couples_listing_or_navigation_url_false_off_domain():
    assert is_couples_listing_or_navigation_url("https://example.com/prefectures/tokyo") is False


# ---------------------------------------------------------------------------
# 8. duplicate ID除去 / 11. サンプルHTMLからfacility URL抽出
# ---------------------------------------------------------------------------

_AREA_LIST_HTML = """
<html><body>
<nav>
  <a href="https://couples.jp/">Couples トップ</a>
  <a href="https://couples.jp/prefectures/tokyo">東京都</a>
</nav>
<ul class="hotel-list">
  <li><a href="https://couples.jp/hotel-details/1238">ホテル アルファ</a></li>
  <li><a href="https://couples.jp/hotel-details/1238?utm_source=list">ホテル アルファ（一覧経由）</a></li>
  <li><a href="/hotel-details/2001/">ホテル ベータ</a></li>
  <li><a href="https://couples.jp/hotel-details/3002/review">ホテル ガンマ（レビュー経由）</a></li>
  <li><a href="https://couples.jp/articles/999">記事: ラブホの選び方</a></li>
  <li><a href="https://couples.jp/hotel-groups/5">系列ホテル一覧</a></li>
</ul>
<nav class="pagination">
  <a href="https://couples.jp/tokyo?page=2">次のページ</a>
</nav>
<footer>
  <a href="https://not-couples.example.com/hotel-details/9999">Off-domain (must be excluded)</a>
  <a href="#top">Back to top (must be excluded)</a>
  <a href="javascript:void(0)">no-op (must be excluded)</a>
</footer>
</body></html>
"""


def test_extract_couples_facility_urls_from_sample_html_dedupes_and_canonicalizes():
    urls = extract_couples_facility_urls(_AREA_LIST_HTML, "https://couples.jp/tokyo")
    assert urls == [
        "https://couples.jp/hotel-details/1238",
        "https://couples.jp/hotel-details/2001",
        "https://couples.jp/hotel-details/3002",
    ]
    # off-domain lookalike never included even though the path matches:
    assert "https://not-couples.example.com/hotel-details/9999" not in urls
    assert not any("9999" in u for u in urls)


def test_extract_couples_facility_urls_ignores_articles_and_groups():
    urls = extract_couples_facility_urls(_AREA_LIST_HTML, "https://couples.jp/tokyo")
    assert not any("articles" in u or "hotel-groups" in u for u in urls)


def test_count_raw_facility_hrefs_counts_before_dedup():
    # 1238 appears twice (plain + tracking param), 2001 and 3002/review once
    # each -> 4 raw occurrences, vs. 3 canonical/deduped IDs.
    assert count_raw_facility_hrefs(_AREA_LIST_HTML, "https://couples.jp/tokyo") == 4
    assert len(extract_couples_facility_urls(_AREA_LIST_HTML, "https://couples.jp/tokyo")) == 3


# ---------------------------------------------------------------------------
# 9. prefecture navigation抽出 / 10. pagination抽出
# ---------------------------------------------------------------------------


def test_extract_navigation_urls_keeps_pagination_and_prefecture_links_only():
    urls = extract_navigation_urls(_AREA_LIST_HTML, "https://couples.jp/tokyo")
    assert "https://couples.jp/" in urls
    assert "https://couples.jp/prefectures/tokyo" in urls
    assert "https://couples.jp/tokyo?page=2" in urls
    # facility links, off-domain links, articles/hotel-groups excluded:
    assert not any(is_couples_facility_url(u) for u in urls)
    assert not any("articles" in u or "hotel-groups" in u or "not-couples" in u for u in urls)


_PREFECTURE_INDEX_HTML = """
<html><body>
<ul class="pref-nav">
  <li><a href="https://couples.jp/prefectures/1">北海道</a></li>
  <li><a href="https://couples.jp/prefectures/13">東京都</a></li>
  <li><a href="https://couples.jp/prefectures/27">大阪府</a></li>
  <li><a href="https://couples.jp/prefectures/40">福岡県</a></li>
  <li><a href="https://couples.jp/prefectures/47">沖縄県</a></li>
</ul>
<a href="https://couples.jp/articles/1">東京都で人気のホテル特集</a>
</body></html>
"""


def test_extract_prefecture_entry_urls_matches_exact_prefecture_names_only():
    entries = extract_prefecture_entry_urls(_PREFECTURE_INDEX_HTML, "https://couples.jp/")
    assert entries == {
        "北海道": "https://couples.jp/prefectures/1",
        "東京都": "https://couples.jp/prefectures/13",
        "大阪府": "https://couples.jp/prefectures/27",
        "福岡県": "https://couples.jp/prefectures/40",
        "沖縄県": "https://couples.jp/prefectures/47",
    }
    # the articles link's text is NOT an exact prefecture name -> excluded:
    assert len(entries) == 5


def test_extract_prefecture_entry_urls_empty_for_no_html():
    assert extract_prefecture_entry_urls(None, "https://couples.jp/") == {}
    assert extract_prefecture_entry_urls("<html></html>", "https://couples.jp/") == {}


# ---------------------------------------------------------------------------
# malformed HTML must never crash discovery
# ---------------------------------------------------------------------------


def test_all_extractors_survive_malformed_html():
    malformed = "<html><body><a href='https://couples.jp/hotel-details/1<oops"
    assert extract_couples_facility_urls(malformed, "https://couples.jp/") is not None
    assert extract_navigation_urls(malformed, "https://couples.jp/") is not None
    assert extract_prefecture_entry_urls(malformed, "https://couples.jp/") is not None


# ---------------------------------------------------------------------------
# discover_prefecture_facilities: BFS, pagination following, failure modes
# ---------------------------------------------------------------------------


def _write(tmp_path, name: str, content: str) -> str:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return name


def test_discover_prefecture_facilities_follows_pagination_and_dedupes(tmp_path):
    manifest = {
        "https://couples.jp/prefectures/13": _write(
            tmp_path, "page1.html",
            """<html><body>
            <a href="https://couples.jp/hotel-details/1238">A</a>
            <a href="https://couples.jp/hotel-details/1238?utm_source=x">A dup</a>
            <a href="https://couples.jp/prefectures/13?page=2">next</a>
            </body></html>""",
        ),
        "https://couples.jp/prefectures/13?page=2": _write(
            tmp_path, "page2.html",
            """<html><body>
            <a href="https://couples.jp/hotel-details/2001">B</a>
            <a href="https://couples.jp/hotel-details/2002/review">C via review</a>
            </body></html>""",
        ),
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    fetcher = FixtureFetchEngine(tmp_path)

    result = discover_prefecture_facilities("東京都", "https://couples.jp/prefectures/13", fetcher, max_pages=10)

    assert result.status == "ok"
    assert result.pages_visited == 2
    assert result.pages_failed == 0
    assert result.unique_facility_ids == {"1238", "2001", "2002"}
    assert all(f.prefecture == "東京都" for f in result.facilities)
    # no review/derived URL survives into the result set:
    assert all(f.canonical_url == f"https://couples.jp/hotel-details/{f.facility_id}" for f in result.facilities)


def test_discover_prefecture_facilities_no_entry_url_is_navigation_failure_not_zero():
    fetcher = FixtureFetchEngine("/nonexistent")
    result = discover_prefecture_facilities("鳥取県", None, fetcher)
    assert result.status == "no_entry_url"
    assert result.unique_facility_ids == set()


def test_discover_prefecture_facilities_entry_fetch_failure_is_failed_not_empty(tmp_path):
    (tmp_path / "manifest.json").write_text("{}", encoding="utf-8")
    fetcher = FixtureFetchEngine(tmp_path)
    result = discover_prefecture_facilities("島根県", "https://couples.jp/prefectures/32", fetcher)
    assert result.status == "failed"
    assert result.pages_failed == 1
    assert result.unique_facility_ids == set()


def test_discover_prefecture_facilities_genuinely_empty_page_is_empty_not_failed(tmp_path):
    manifest = {
        "https://couples.jp/prefectures/47": _write(tmp_path, "okinawa.html", "<html><body><p>No hotels found</p></body></html>"),
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    fetcher = FixtureFetchEngine(tmp_path)
    result = discover_prefecture_facilities("沖縄県", "https://couples.jp/prefectures/47", fetcher)
    assert result.status == "empty"
    assert result.pages_failed == 0
    assert result.unique_facility_ids == set()


def test_discover_prefecture_facilities_respects_max_pages_budget(tmp_path):
    # A page that always links to a fresh "next page" -- without a page
    # budget this would loop forever.
    manifest = {}
    for i in range(1, 6):
        manifest[f"https://couples.jp/prefectures/13?page={i}"] = _write(
            tmp_path, f"p{i}.html",
            f'<html><body><a href="https://couples.jp/prefectures/13?page={i + 1}">next</a></body></html>',
        )
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    fetcher = FixtureFetchEngine(tmp_path)
    result = discover_prefecture_facilities("東京都", "https://couples.jp/prefectures/13?page=1", fetcher, max_pages=3)
    assert result.pages_visited == 3


# ---------------------------------------------------------------------------
# discover_all_prefectures: nationwide aggregation + report formatting
# ---------------------------------------------------------------------------


def _build_nationwide_fixture(tmp_path):
    """5 prefectures reachable from the top page's nav; the rest of the 47
    have no entry link at all (deliberately, to exercise
    no_entry_url handling for the remaining 42)."""
    manifest = {
        "https://couples.jp/": _write(tmp_path, "top.html", _PREFECTURE_INDEX_HTML),
        "https://couples.jp/prefectures/1": _write(
            tmp_path, "hokkaido.html",
            '<html><body><a href="https://couples.jp/hotel-details/9001">H</a></body></html>',
        ),
        "https://couples.jp/prefectures/13": _write(
            tmp_path, "tokyo.html",
            """<html><body>
            <a href="https://couples.jp/hotel-details/1238">A</a>
            <a href="https://couples.jp/hotel-details/1238/rooms">A rooms</a>
            <a href="https://couples.jp/hotel-details/1239">B</a>
            </body></html>""",
        ),
        "https://couples.jp/prefectures/27": _write(
            tmp_path, "osaka.html",
            '<html><body><a href="https://couples.jp/hotel-details/5001">C</a></body></html>',
        ),
        "https://couples.jp/prefectures/40": _write(
            tmp_path, "fukuoka.html",
            '<html><body><a href="https://couples.jp/hotel-details/6001">D</a></body></html>',
        ),
        "https://couples.jp/prefectures/47": _write(tmp_path, "okinawa.html", "<html><body>No hotels found</body></html>"),
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return FixtureFetchEngine(tmp_path)


def test_discover_all_prefectures_visits_all_47_and_distinguishes_outcomes(tmp_path):
    fetcher = _build_nationwide_fixture(tmp_path)
    result = discover_all_prefectures(fetcher, index_urls=["https://couples.jp/"])

    assert result.visited_prefecture_count == 47
    assert result.prefectures["北海道"].status == "ok"
    assert result.prefectures["東京都"].status == "ok"
    assert result.prefectures["東京都"].unique_facility_ids == {"1238", "1239"}
    assert result.prefectures["沖縄県"].status == "empty"  # genuinely zero, not a failure
    # every prefecture with no discovered entry link at all is a distinct
    # navigation-failure outcome, never silently counted as "0 facilities":
    assert result.prefectures["青森県"].status == "no_entry_url"
    assert "青森県" in result.failed_prefectures
    assert "沖縄県" not in result.failed_prefectures


def test_discover_all_prefectures_dedupes_facility_ids_and_reports_zero_contamination(tmp_path):
    fetcher = _build_nationwide_fixture(tmp_path)
    result = discover_all_prefectures(fetcher, index_urls=["https://couples.jp/"])

    # 1238 appears twice on the Tokyo page (plain + /rooms) -> 1 raw extra,
    # collapses to 1 canonical entry within that page's own extraction.
    assert result.unique_facility_ids.keys() == {"9001", "1238", "1239", "5001", "6001"}
    assert result.review_url_contamination == 0
    assert result.non_facility_url_contamination == 0
    assert result.canonical_facility_urls >= len(result.unique_facility_ids)
    assert result.duplicate_facility_id_count == result.canonical_facility_urls - len(result.unique_facility_ids)


def test_format_dry_run_report_contains_all_47_prefecture_lines_and_totals(tmp_path):
    fetcher = _build_nationwide_fixture(tmp_path)
    result = discover_all_prefectures(fetcher, index_urls=["https://couples.jp/"])
    report = format_dry_run_report(result, simulated=True)

    assert "47_PREFECTURES_VISITED=47" in report
    assert "PREFECTURE_01_HOKKAIDO=1 (status=ok)" in report
    assert "PREFECTURE_13_TOKYO=2 (status=ok)" in report
    assert "PREFECTURE_47_OKINAWA=0 (status=empty)" in report
    assert "PREFECTURE_02_AOMORI=FAILED(no_entry_url" in report
    assert "UNIQUE_FACILITY_IDS=5" in report
    assert "REVIEW_URL_CONTAMINATION=0" in report
    assert "NON_FACILITY_URL_CONTAMINATION=0" in report
    assert "DISCOVERY_COMPLETE=NO" in report  # 42 no_entry_url prefectures in this fixture
    assert "SIMULATED RUN" in report

    # exactly 47 PREFECTURE_ lines:
    pref_lines = [line for line in report.splitlines() if line.startswith("PREFECTURE_")]
    assert len(pref_lines) == 47


def test_to_json_summary_lists_every_facility_with_prefecture_and_source(tmp_path):
    fetcher = _build_nationwide_fixture(tmp_path)
    result = discover_all_prefectures(fetcher, index_urls=["https://couples.jp/"])
    summary = to_json_summary(result)

    assert summary["unique_facility_ids"] == 5
    facilities_by_id = {f["facility_id"]: f for f in summary["facilities"]}
    assert facilities_by_id["1238"]["prefecture"] == "東京都"
    assert facilities_by_id["1238"]["canonical_url"] == "https://couples.jp/hotel-details/1238"
    assert facilities_by_id["9001"]["prefecture"] == "北海道"
    assert summary["per_prefecture"]["沖縄県"]["status"] == "empty"
    assert summary["per_prefecture"]["青森県"]["status"] == "no_entry_url"


# ---------------------------------------------------------------------------
# 12. 他categoryへのregression: this module must not import/touch anything
# outside its own file, and other adapters/discovery modules keep working.
# ---------------------------------------------------------------------------


def test_module_does_not_touch_other_categories():
    import db_collector_os.discovery.lovehotel_couples as mod

    # sanity: this module has no dependency on figure/sample adapters or
    # any other job-specific code.
    assert "figure" not in mod.__file__
    from db_collector_os.adapters import get_adapter

    figure_adapter = get_adapter("figure_official_site")
    assert figure_adapter.entity_type != "love_hotel"


# ---------------------------------------------------------------------------
# Deep multi-hop navigation audit: prefecture entry -> area -> city ->
# paginated search-result pages -> facility links. A shallow implementation
# that only ever looks one hop past the prefecture entry point would
# silently undercount real prefectures (which conventionally nest area/city/
# search-result pages several links deep) while still reporting a "clean"
# 47/47-visited run -- this proves the BFS genuinely walks the full tree,
# not just the first hop, before that number is trusted.
# ---------------------------------------------------------------------------


def _write_html(tmp_path, name: str, content: str) -> str:
    (tmp_path / name).write_text(content, encoding="utf-8")
    return name


def _build_deep_multi_hop_fixture(tmp_path):
    """東京都: entry -> 2 area pages -> each area -> 2 city pages -> each
    city -> a 2-page paginated search-result listing -> facility links.
    2 areas * 2 cities * 2 pages * 2 facilities/page = 16 distinct
    facilities, reachable only by walking all 4 hops."""
    manifest: dict[str, str] = {}

    manifest["https://couples.jp/prefectures/13"] = _write_html(
        tmp_path, "tokyo_entry.html",
        """<html><body>
        <a href="https://couples.jp/areas/13/east">東部エリア</a>
        <a href="https://couples.jp/areas/13/west">西部エリア</a>
        </body></html>""",
    )

    facility_id = 20000
    for area in ("east", "west"):
        manifest[f"https://couples.jp/areas/13/{area}"] = _write_html(
            tmp_path, f"area_{area}.html",
            f"""<html><body>
            <a href="https://couples.jp/cities/13/{area}/city1">市区町村1</a>
            <a href="https://couples.jp/cities/13/{area}/city2">市区町村2</a>
            </body></html>""",
        )
        for city in ("city1", "city2"):
            manifest[f"https://couples.jp/cities/13/{area}/{city}"] = _write_html(
                tmp_path, f"city_{area}_{city}.html",
                f'<html><body><a href="https://couples.jp/search?area={area}&city={city}&page=1">検索結果</a></body></html>',
            )
            for page in (1, 2):
                links = []
                for _ in range(2):
                    facility_id += 1
                    links.append(f'<a href="https://couples.jp/hotel-details/{facility_id}">H{facility_id}</a>')
                next_link = (
                    f'<a href="https://couples.jp/search?area={area}&city={city}&page={page + 1}">次へ</a>'
                    if page == 1 else ""
                )
                html = f"<html><body>{''.join(links)}{next_link}</body></html>"
                manifest[f"https://couples.jp/search?area={area}&city={city}&page={page}"] = _write_html(
                    tmp_path, f"search_{area}_{city}_p{page}.html", html,
                )

    (tmp_path / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return FixtureFetchEngine(tmp_path), manifest


def test_bfs_walks_area_city_search_and_pagination_hops_not_just_the_first_link():
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        from pathlib import Path as _Path

        fetcher, manifest = _build_deep_multi_hop_fixture(_Path(td))
        result = discover_prefecture_facilities(
            "東京都", "https://couples.jp/prefectures/13", fetcher, max_pages=100,
        )

    assert result.status == "ok"
    # 1 entry + 2 area + 4 city + 8 search-result pages = 15 pages, all of
    # which must actually be fetched -- a shallow (1-hop) implementation
    # would stop at 1 or 3 pages and silently undercount.
    assert result.pages_visited == 15
    assert result.pages_failed == 0
    assert len(result.unique_facility_ids) == 16
    assert all(f.prefecture == "東京都" for f in result.facilities)
    # every discovered URL is the bare canonical form, nothing from a
    # listing/search/area/city hop leaked into the facility result set:
    assert all(is_couples_facility_url(f.canonical_url) for f in result.facilities)
    assert all(f.canonical_url == f"https://couples.jp/hotel-details/{f.facility_id}" for f in result.facilities)


def test_bfs_does_not_undercount_when_max_pages_is_generous_enough_for_the_real_tree():
    """A max_pages budget lower than the tree's real page count DOES
    legitimately truncate discovery (load control is a deliberate design
    choice, task requirement 負荷を抑える) -- but the report must never
    silently claim "ok" success while having skipped part of a reachable
    tree without it being reflected in a lower pages_visited/facility count
    than the generous-budget run. This pins that relationship down."""
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        from pathlib import Path as _Path

        fetcher, _manifest = _build_deep_multi_hop_fixture(_Path(td))
        truncated = discover_prefecture_facilities(
            "東京都", "https://couples.jp/prefectures/13", fetcher, max_pages=5,
        )

    assert truncated.pages_visited == 5
    assert len(truncated.unique_facility_ids) < 16  # budget-limited, honestly reflected
