"""spec section 36: a validation run must not crash on robots-block,
timeout, 404, redirect, duplicate, noindex, non-HTML, or malformed-HTML
responses -- each is a normal, already-handled crawl outcome (reused from
PHASE 1's existing crawler), and the run must still complete and report
results for whatever it *did* manage to fetch.
"""
from __future__ import annotations

import responses

from db_collector_os.competitive_intelligence.validation import ValidationOptions, run_validation
from db_collector_os.competitive_intelligence.validation.repository import ValidationRunRepository

_BASE = "https://failure-fixture.example"
_GOOD_HTML = (
    "<!doctype html><html><head><title>おすすめ 健康グッズ 比較</title></head><body>"
    "<main><h1>おすすめ健康グッズ比較</h1><p>編集部が実際に選んだおすすめの健康グッズを比較して紹介する記事です。"
    "実際の使用感やレビューをもとにまとめました。</p></main></body></html>"
)


def test_robots_txt_blocks_all_pages_still_completes(db):
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(responses.GET, f"{_BASE}/robots.txt", body="User-agent: *\nDisallow: /\n", content_type="text/plain")
        rsps.add(responses.GET, f"{_BASE}/sitemap.xml", status=404)
        validation_run_id = run_validation(db, f"{_BASE}/", ValidationOptions(max_pages=30))
    run = ValidationRunRepository(db).get(validation_run_id)
    assert run["status"] in ("COMPLETED", "FAILED")  # never crashes/raises
    assert run["production_validation_status"] in ("PASS", "CONDITIONAL_PASS", "FAIL")


def test_connection_error_treated_as_fetch_failure_not_a_crash(db):
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(responses.GET, f"{_BASE}/robots.txt", status=404)
        rsps.add(responses.GET, f"{_BASE}/sitemap.xml", status=404)
        rsps.add(responses.GET, f"{_BASE}/", body=ConnectionError("simulated timeout"))
        validation_run_id = run_validation(db, f"{_BASE}/", ValidationOptions(max_pages=30))
    run = ValidationRunRepository(db).get(validation_run_id)
    assert run["status"] == "FAILED"
    assert run["error_message"] is not None or run["summary_json"] is not None


def test_404_pages_excluded_but_run_completes(db):
    home = (
        f'<!doctype html><html><head><title>t</title></head><body><main><h1>ホーム</h1>'
        f'<p>{_GOOD_HTML}</p><a href="{_BASE}/missing.html">missing</a>'
        f'<a href="{_BASE}/article/">記事</a></main></body></html>'
    )
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(responses.GET, f"{_BASE}/robots.txt", status=404)
        rsps.add(responses.GET, f"{_BASE}/sitemap.xml", status=404)
        rsps.add(responses.GET, f"{_BASE}/", body=home, content_type="text/html")
        rsps.add(responses.GET, f"{_BASE}/missing.html", status=404)
        rsps.add(responses.GET, f"{_BASE}/article/", body=_GOOD_HTML, content_type="text/html")
        validation_run_id = run_validation(db, f"{_BASE}/", ValidationOptions(max_pages=30))
    run = ValidationRunRepository(db).get(validation_run_id)
    assert run["status"] == "COMPLETED"


def test_redirect_followed_and_counted(db):
    home = (
        f'<!doctype html><html><head><title>t</title></head><body><main><h1>ホーム</h1>'
        f'<a href="{_BASE}/old-article/">記事</a></main></body></html>'
    )
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(responses.GET, f"{_BASE}/robots.txt", status=404)
        rsps.add(responses.GET, f"{_BASE}/sitemap.xml", status=404)
        rsps.add(responses.GET, f"{_BASE}/", body=home, content_type="text/html")
        rsps.add(
            responses.GET, f"{_BASE}/old-article/", status=301,
            headers={"Location": f"{_BASE}/article/"},
        )
        rsps.add(responses.GET, f"{_BASE}/article/", body=_GOOD_HTML, content_type="text/html")
        validation_run_id = run_validation(db, f"{_BASE}/", ValidationOptions(max_pages=30))
    run = ValidationRunRepository(db).get(validation_run_id)
    assert run["status"] == "COMPLETED"


def test_noindex_page_excluded_from_analysis_but_run_completes(db):
    home = (
        f'<!doctype html><html><head><title>t</title></head><body><main><h1>ホーム</h1>'
        f'<a href="{_BASE}/noindex-page/">noindex</a><a href="{_BASE}/article/">記事</a></main></body></html>'
    )
    noindex_page = (
        '<!doctype html><html><head><title>t</title><meta name="robots" content="noindex"></head>'
        f"<body>{_GOOD_HTML}</body></html>"
    )
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(responses.GET, f"{_BASE}/robots.txt", status=404)
        rsps.add(responses.GET, f"{_BASE}/sitemap.xml", status=404)
        rsps.add(responses.GET, f"{_BASE}/", body=home, content_type="text/html")
        rsps.add(responses.GET, f"{_BASE}/noindex-page/", body=noindex_page, content_type="text/html")
        rsps.add(responses.GET, f"{_BASE}/article/", body=_GOOD_HTML, content_type="text/html")
        validation_run_id = run_validation(db, f"{_BASE}/", ValidationOptions(max_pages=30))
    run = ValidationRunRepository(db).get(validation_run_id)
    assert run["status"] == "COMPLETED"
    noindex_row = db.query_one(
        "SELECT indexable FROM ci_crawl_urls WHERE crawl_run_id=? AND url=?",
        (run["crawl_run_id"], f"{_BASE}/noindex-page/"),
    )
    assert noindex_row["indexable"] == 0


def test_non_html_content_type_not_treated_as_a_page(db):
    home = (
        f'<!doctype html><html><head><title>t</title></head><body><main><h1>ホーム</h1>'
        f'<a href="{_BASE}/image.png">img</a><a href="{_BASE}/article/">記事</a></main></body></html>'
    )
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(responses.GET, f"{_BASE}/robots.txt", status=404)
        rsps.add(responses.GET, f"{_BASE}/sitemap.xml", status=404)
        rsps.add(responses.GET, f"{_BASE}/", body=home, content_type="text/html")
        rsps.add(responses.GET, f"{_BASE}/image.png", body=b"\x89PNG\r\n", content_type="image/png")
        rsps.add(responses.GET, f"{_BASE}/article/", body=_GOOD_HTML, content_type="text/html")
        validation_run_id = run_validation(db, f"{_BASE}/", ValidationOptions(max_pages=30))
    run = ValidationRunRepository(db).get(validation_run_id)
    assert run["status"] == "COMPLETED"
    page_types = {r["page_id"] for r in db.query(
        "SELECT page_id FROM ci_pages WHERE crawl_run_id=? AND url=?", (run["crawl_run_id"], f"{_BASE}/image.png")
    )}
    assert not page_types, "a non-HTML response must never become an analyzed page"


def test_malformed_html_does_not_crash_the_run(db):
    home = (
        f'<!doctype html><html><head><title>t</title></head><body><main><h1>ホーム</h1>'
        f'<a href="{_BASE}/broken/">壊れたページ</a></main></body></html>'
    )
    broken_html = "<html><body><main><h1>タイトル<p>閉じタグ忘れ<div>ネスト崩れ</main>"
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(responses.GET, f"{_BASE}/robots.txt", status=404)
        rsps.add(responses.GET, f"{_BASE}/sitemap.xml", status=404)
        rsps.add(responses.GET, f"{_BASE}/", body=home, content_type="text/html")
        rsps.add(responses.GET, f"{_BASE}/broken/", body=broken_html, content_type="text/html")
        validation_run_id = run_validation(db, f"{_BASE}/", ValidationOptions(max_pages=30))
    run = ValidationRunRepository(db).get(validation_run_id)
    assert run["status"] == "COMPLETED"


def test_duplicate_normalized_url_deduplicated(db):
    home = (
        f'<!doctype html><html><head><title>t</title></head><body><main><h1>ホーム</h1>'
        f'<a href="{_BASE}/article/">記事</a><a href="{_BASE}/article/?utm_source=x">記事(utm付き)</a>'
        "</main></body></html>"
    )
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(responses.GET, f"{_BASE}/robots.txt", status=404)
        rsps.add(responses.GET, f"{_BASE}/sitemap.xml", status=404)
        rsps.add(responses.GET, f"{_BASE}/", body=home, content_type="text/html")
        rsps.add(responses.GET, f"{_BASE}/article/", body=_GOOD_HTML, content_type="text/html")
        validation_run_id = run_validation(db, f"{_BASE}/", ValidationOptions(max_pages=30))
    run = ValidationRunRepository(db).get(validation_run_id)
    assert run["status"] == "COMPLETED"
    article_pages = db.query(
        "SELECT page_id FROM ci_pages WHERE crawl_run_id=? AND normalized_url LIKE ?",
        (run["crawl_run_id"], f"{_BASE}/article%"),
    )
    assert len(article_pages) == 1, "utm-tracking-param URL must normalize to the same page, not duplicate it"


def test_zero_pages_fetched_reports_fail_not_a_crash(db):
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(responses.GET, f"{_BASE}/robots.txt", status=404)
        rsps.add(responses.GET, f"{_BASE}/sitemap.xml", status=404)
        rsps.add(responses.GET, f"{_BASE}/", status=500)
        validation_run_id = run_validation(db, f"{_BASE}/", ValidationOptions(max_pages=30))
    run = ValidationRunRepository(db).get(validation_run_id)
    assert run["status"] == "FAILED"
    assert run["production_validation_status"] == "FAIL"
