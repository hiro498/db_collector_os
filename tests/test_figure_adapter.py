"""Unit tests for the FIRST_PRODUCTION_DB adapter: figure_official_site.

Covers list vs. detail pages, full/partial/duplicate/noisy/unparsable
structured data -- all against local fixtures, no live network access.
"""

from __future__ import annotations

from pathlib import Path

from db_collector_os.adapters import get_adapter, list_adapters
from db_collector_os.adapters.registry import _REGISTRY
from db_collector_os.deduplication import compute_fingerprint
from db_collector_os.extraction.common import extract_common

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


def test_adapter_is_registered():
    assert "figure_official_site" in list_adapters()
    adapter = get_adapter("figure_official_site")
    assert adapter.name == "figure_official_site"
    assert adapter.entity_type == "figure"
    assert _REGISTRY["figure_official_site"] is type(adapter)


def test_list_page_is_skipped_not_sent_to_review():
    html = load_fixture("figure_list.html")
    adapter = get_adapter("figure_official_site")
    common = extract_common(html, "https://figures.example.com/products/")
    record = adapter.extract(common, "https://figures.example.com/products/", html)
    assert record.skip is True
    assert record.skip_reason
    assert not record.missing_required  # skip, not a review-worthy failure


def test_list_page_links_are_still_discoverable():
    html = load_fixture("figure_list.html")
    common = extract_common(html, "https://figures.example.com/products/")
    assert "https://figures.example.com/products/hana-1-7/" in common["links"]
    assert "https://figures.example.com/products/yuki-1-8/" in common["links"]


def test_full_detail_page_extracts_all_fields():
    html = load_fixture("figure_detail_full.html")
    adapter = get_adapter("figure_official_site")
    common = extract_common(html, "https://figures.example.com/products/hana-1-7/")
    record = adapter.extract(common, "https://figures.example.com/products/hana-1-7/", html)

    assert record.skip is False
    assert not record.missing_required
    assert record.name == "花 1/7スケールフィギュア"
    assert record.canonical_url == "https://figures.example.com/products/hana-1-7/"
    assert record.external_id == "4900000012345"  # gtin13 wins over sku/mpn
    assert record.fields["brand"] == "Example Figure Works"
    assert record.fields["manufacturer"] == "Example Figure Works"
    assert record.fields["series"] == "サンプルアニメ"
    assert record.fields["scale"] == "1/7"
    assert record.fields["sku"] == "EFW-HANA-001"
    assert record.fields["gtin"] == "4900000012345"
    assert record.fields["price"] == "24200"
    assert record.fields["currency"] == "JPY"
    assert record.fields["availability"] == "https://schema.org/PreOrder"
    assert record.fields["release_date"] == "2026-11-01"
    assert len(record.fields["image_urls"]) == 2


def test_missing_name_routes_to_review_not_skip():
    html = load_fixture("figure_detail_missing_name.html")
    adapter = get_adapter("figure_official_site")
    common = extract_common(html, "https://figures.example.com/products/broken-listing/")
    record = adapter.extract(common, "https://figures.example.com/products/broken-listing/", html)

    assert record.skip is False  # a Product block WAS present -> not a "non-entity page"
    assert record.missing_required == ["name"]


def test_duplicate_product_shares_fingerprint_via_gtin():
    original_html = load_fixture("figure_detail_full.html")
    dup_html = load_fixture("figure_detail_duplicate.html")
    adapter = get_adapter("figure_official_site")

    common1 = extract_common(original_html, "https://figures.example.com/products/hana-1-7/")
    record1 = adapter.extract(common1, "https://figures.example.com/products/hana-1-7/", original_html)

    common2 = extract_common(dup_html, "https://figures.example.com/products/hana-1-7-rerelease/")
    record2 = adapter.extract(common2, "https://figures.example.com/products/hana-1-7-rerelease/", dup_html)

    assert record1.external_id == record2.external_id == "4900000012345"
    assert record1.canonical_url != record2.canonical_url  # different URLs, same real-world product
    fp1 = compute_fingerprint(record1.entity_type, external_id=record1.external_id)
    fp2 = compute_fingerprint(record2.entity_type, external_id=record2.external_id)
    assert fp1 == fp2


def test_noisy_multi_jsonld_page_still_finds_the_product_block():
    html = load_fixture("figure_detail_noisy.html")
    adapter = get_adapter("figure_official_site")
    common = extract_common(html, "https://figures.example.com/products/yuki-1-8/")
    record = adapter.extract(common, "https://figures.example.com/products/yuki-1-8/", html)

    assert record.skip is False
    assert not record.missing_required
    assert record.name == "雪 1/8スケールフィギュア"
    assert record.fields["series"] == "サンプルアニメ2"
    assert record.fields["sku"] == "EFW-YUKI-002"
    # Organization / BreadcrumbList blocks on the same page must not leak in.
    assert len(common["json_ld"]) == 3


def test_unparsable_jsonld_does_not_crash_and_is_skipped():
    html = load_fixture("figure_detail_unparsable.html")
    adapter = get_adapter("figure_official_site")
    common = extract_common(html, "https://figures.example.com/products/broken-json/")
    record = adapter.extract(common, "https://figures.example.com/products/broken-json/", html)

    assert record.skip is True
    assert common["json_ld"] == []  # the malformed block was dropped, not raised


def test_seed_urls_come_from_job_config():
    adapter = get_adapter("figure_official_site")
    job = {"config_json": {"seed_urls": ["https://figures.example.com/products/"]}}
    assert adapter.seed_urls(job) == ["https://figures.example.com/products/"]


def test_required_fields_is_name_only():
    adapter = get_adapter("figure_official_site")
    assert adapter.required_fields == ("name",)
