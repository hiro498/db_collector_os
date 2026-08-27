"""Adapter tests against a Good Smile Company-shaped fixture (see
tests/fixtures/goodsmile_product_1141716.html for provenance notes -- it is
a reconstruction from the confirmed production proof, not a live scrape).

Covers: JSON-LD as primary source, dataLayer (GA4 Enhanced Ecommerce
convention) as a safe fallback for fields JSON-LD omitted, HTML entity
decoding, discovery URL extraction, duplicate suppression via a shared
stable identifier, malformed structured data, and missing optional fields.
"""

from __future__ import annotations

from pathlib import Path

from db_collector_os.adapters import get_adapter
from db_collector_os.deduplication import compute_fingerprint
from db_collector_os.extraction.common import extract_common
from db_collector_os.extraction.datalayer import extract_data_layer_items

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


GS_URL = "https://www.goodsmile.com/en/product/1141716/Rikka%2BTakarada%2BAkane%2BShinjo%2Bfeat.%2Btoridamono"


def test_goodsmile_fixture_extracts_decoded_name_and_json_ld_fields():
    html = load_fixture("goodsmile_product_1141716.html")
    adapter = get_adapter("figure_official_site")
    common = extract_common(html, GS_URL)
    record = adapter.extract(common, GS_URL, html)

    assert record.skip is False
    assert not record.missing_required
    assert record.name == "Rikka Takarada & Akane Shinjo feat. toridamono"
    assert "&amp;" not in record.name
    assert record.fields["brand"] == "Good Smile Company"
    assert record.fields["sku"] == "1141716"
    assert record.fields["price"] == "259.99"
    assert record.fields["currency"] == "USD"
    assert record.fields["availability"] == "https://schema.org/PreOrder"
    assert len(record.fields["image_urls"]) == 2


def test_goodsmile_fixture_falls_back_to_datalayer_for_missing_fields():
    """JSON-LD on this fixture has no category/mpn/gtin/releaseDate --
    those (and reservation_deadline, which has no JSON-LD equivalent at
    all) must come from the dataLayer fallback.
    """
    html = load_fixture("goodsmile_product_1141716.html")
    adapter = get_adapter("figure_official_site")
    common = extract_common(html, GS_URL)
    record = adapter.extract(common, GS_URL, html)

    assert record.fields["series"] == "Scale Figures"  # item_category2 preferred over item_category
    assert record.fields["category_l1"] == "Figures"
    assert record.fields["category_l2"] == "Scale Figures"
    assert record.fields["product_master_code"] == "GSC-RTAS-1141716"
    assert record.fields["reservation_deadline"] == "2026-12-25"
    # JSON-LD's own sku/price/brand must NOT be overridden by dataLayer:
    assert record.fields["sku"] == "1141716"
    assert record.fields["price"] == "259.99"
    assert record.fields["brand"] == "Good Smile Company"


def test_datalayer_fallback_only_fills_gaps_never_overrides_json_ld():
    html_jsonld_has_category = """
    <html><head><meta charset="utf-8">
    <script type="application/ld+json">
    {"@type": "Product", "name": "Widget", "category": "JSON-LD Category", "sku": "SKU-1",
     "offers": {"price": "10.00", "priceCurrency": "USD"}}
    </script>
    <script>
    dataLayer.push({"ecommerce": {"items": [{"item_category2": "DataLayer Category", "price": 99.99}]}});
    </script>
    </head><body></body></html>
    """
    adapter = get_adapter("figure_official_site")
    common = extract_common(html_jsonld_has_category, "https://example.com/p")
    record = adapter.extract(common, "https://example.com/p", html_jsonld_has_category)
    assert record.fields["series"] == "JSON-LD Category"  # JSON-LD wins, not overridden
    assert record.fields["price"] == "10.00"


def test_no_datalayer_on_page_is_a_safe_no_op():
    html = """
    <html><head><meta charset="utf-8">
    <script type="application/ld+json">
    {"@type": "Product", "name": "Widget", "sku": "SKU-1"}
    </script>
    </head><body></body></html>
    """
    adapter = get_adapter("figure_official_site")
    common = extract_common(html, "https://example.com/p")
    record = adapter.extract(common, "https://example.com/p", html)
    assert record.name == "Widget"
    assert record.fields["reservation_deadline"] is None
    assert record.fields["product_master_code"] is None


def test_malformed_datalayer_js_is_skipped_gracefully():
    """Unquoted keys make this invalid JSON -- extract_data_layer_items must
    skip it rather than guess, and the adapter must still succeed via JSON-LD.
    """
    html = """
    <html><head><meta charset="utf-8">
    <script type="application/ld+json">
    {"@type": "Product", "name": "Widget", "sku": "SKU-1"}
    </script>
    <script>
    dataLayer.push({ecommerce: {items: [{item_category2: 'Bad JS Object'}]}});
    </script>
    </head><body></body></html>
    """
    items = extract_data_layer_items(html)
    assert items == []
    adapter = get_adapter("figure_official_site")
    common = extract_common(html, "https://example.com/p")
    record = adapter.extract(common, "https://example.com/p", html)
    assert record.skip is False
    assert record.name == "Widget"
    assert record.fields["series"] is None


def test_malformed_json_ld_falls_back_to_skip_not_crash():
    html = """
    <html><head><meta charset="utf-8">
    <script type="application/ld+json">
    { "@type": "Product", "name": "Broken"
    </script>
    </head><body></body></html>
    """
    adapter = get_adapter("figure_official_site")
    common = extract_common(html, "https://example.com/broken")
    record = adapter.extract(common, "https://example.com/broken", html)
    assert record.skip is True


def test_discovery_url_extraction_from_goodsmile_fixture():
    html = load_fixture("goodsmile_product_1141716.html")
    common = extract_common(html, GS_URL)
    assert "https://www.goodsmile.com/en/products/category/figures" in common["links"]
    assert "https://www.goodsmile.com/en/product/1141717/related-item" in common["links"]


def test_duplicate_across_pages_shares_fingerprint_via_sku():
    html1 = load_fixture("goodsmile_product_1141716.html")
    html2 = html1.replace(
        'href="https://www.goodsmile.com/en/product/1141716/Rikka%2BTakarada%2BAkane%2BShinjo%2Bfeat.%2Btoridamono"',
        'href="https://www.goodsmile.com/en/product/1141716/alternate-slug"',
    )
    adapter = get_adapter("figure_official_site")

    common1 = extract_common(html1, GS_URL)
    record1 = adapter.extract(common1, GS_URL, html1)

    alt_url = "https://www.goodsmile.com/en/product/1141716/alternate-slug"
    common2 = extract_common(html2, alt_url)
    record2 = adapter.extract(common2, alt_url, html2)

    assert record1.external_id == record2.external_id == "1141716"
    fp1 = compute_fingerprint(record1.entity_type, external_id=record1.external_id)
    fp2 = compute_fingerprint(record2.entity_type, external_id=record2.external_id)
    assert fp1 == fp2


def test_missing_optional_fields_do_not_count_as_failure():
    """Only `name` is required -- every other field may legitimately be NULL
    without the record being treated as a failed extraction.
    """
    html = """
    <html><head><meta charset="utf-8">
    <script type="application/ld+json">
    {"@type": "Product", "name": "Bare Minimum Figure"}
    </script>
    </head><body></body></html>
    """
    adapter = get_adapter("figure_official_site")
    common = extract_common(html, "https://example.com/bare")
    record = adapter.extract(common, "https://example.com/bare", html)
    assert record.skip is False
    assert not record.missing_required
    assert record.name == "Bare Minimum Figure"
    assert record.external_id is None
    for optional_field in ("brand", "manufacturer", "series", "scale", "sku", "mpn", "gtin", "price"):
        assert record.fields[optional_field] is None
