from __future__ import annotations

from db_collector_os.competitive_intelligence.enums import ExclusionReason
from db_collector_os.competitive_intelligence.url_tools import (
    classify_non_crawlable,
    is_pagination_url,
    is_same_host,
    normalize_url,
    url_slug,
)


def test_normalize_url_strips_fragment_and_tracking_params():
    url = "https://Example.jp/path/?utm_source=x&b=2&a=1#section"
    assert normalize_url(url) == "https://example.jp/path?a=1&b=2"


def test_normalize_url_reused_from_existing_normalization_module():
    from db_collector_os.normalization.url import normalize_url as core_normalize_url

    assert normalize_url is core_normalize_url


def test_is_same_host_excludes_subdomain():
    assert is_same_host("https://example.jp/a", "example.jp") is True
    assert is_same_host("https://sub.example.jp/a", "example.jp") is False
    assert is_same_host("https://notexample.jp/a", "example.jp") is False


def test_classify_non_crawlable_excludes_subdomain():
    assert classify_non_crawlable("https://sub.example.jp/x", "example.jp") == ExclusionReason.SUBDOMAIN


def test_classify_non_crawlable_excludes_external_domain():
    assert classify_non_crawlable("https://other.com/x", "example.jp") == ExclusionReason.EXTERNAL_DOMAIN


def test_classify_non_crawlable_excludes_assets():
    assert classify_non_crawlable("https://example.jp/logo.png", "example.jp") == ExclusionReason.NON_HTML_ASSET
    assert classify_non_crawlable("https://example.jp/app.js", "example.jp") == ExclusionReason.NON_HTML_ASSET


def test_classify_non_crawlable_excludes_mailto_tel_javascript():
    assert classify_non_crawlable("mailto:info@example.jp", "example.jp") == ExclusionReason.MAILTO
    assert classify_non_crawlable("tel:0120123456", "example.jp") == ExclusionReason.TEL
    assert classify_non_crawlable("javascript:void(0)", "example.jp") == ExclusionReason.JAVASCRIPT_URL


def test_classify_non_crawlable_excludes_admin_paths():
    assert classify_non_crawlable("https://example.jp/wp-admin/", "example.jp") == ExclusionReason.ADMIN_URL


def test_classify_non_crawlable_allows_ordinary_html_url():
    assert classify_non_crawlable("https://example.jp/article/1", "example.jp") is None


def test_is_pagination_url_detects_common_patterns():
    assert is_pagination_url("https://example.jp/list/?page=2") is True
    assert is_pagination_url("https://example.jp/list/page/3/") is True
    assert is_pagination_url("https://example.jp/list/p2/") is True
    assert is_pagination_url("https://example.jp/article/1") is False


def test_url_slug_extracts_last_path_segment():
    assert url_slug("https://example.jp/category/ramen-ranking/") == "ramen-ranking"
    assert url_slug("https://example.jp/") == ""
