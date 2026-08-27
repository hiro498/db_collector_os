"""Regression tests for the HTML-entity-decode fix: a real-world quirk seen
on the first production DB (Good Smile Company) where the site's templating
auto-escaped even the JSON-LD <script> payload, leaving literal "&amp;" in
otherwise-valid JSON string values (e.g. product names with an ampersand).
"""

from __future__ import annotations

from db_collector_os.adapters import get_adapter
from db_collector_os.extraction.common import extract_common
from db_collector_os.extraction.jsonld import extract_json_ld
from db_collector_os.normalization import decode_html_entities, decode_html_entities_deep
from bs4 import BeautifulSoup


def test_decode_html_entities_basic():
    assert decode_html_entities("Rikka &amp; Akane") == "Rikka & Akane"
    assert decode_html_entities("&lt;script&gt;") == "<script>"
    assert decode_html_entities("O&#39;Brien") == "O'Brien"


def test_decode_html_entities_is_idempotent_and_none_safe():
    assert decode_html_entities(None) is None
    assert decode_html_entities("") == ""
    already_clean = "Rikka & Akane"
    assert decode_html_entities(already_clean) == already_clean
    assert decode_html_entities(decode_html_entities("Rikka &amp; Akane")) == "Rikka & Akane"


def test_decode_html_entities_deep_walks_nested_structures():
    data = {
        "name": "Rikka &amp; Akane",
        "brand": {"name": "Good Smile &amp; Company"},
        "image": ["a&amp;b.jpg", "c.jpg"],
        "offers": {"price": "5800", "priceCurrency": "JPY"},
        "count": 3,
        "flag": True,
        "missing": None,
    }
    decoded = decode_html_entities_deep(data)
    assert decoded["name"] == "Rikka & Akane"
    assert decoded["brand"]["name"] == "Good Smile & Company"
    assert decoded["image"] == ["a&b.jpg", "c.jpg"]
    assert decoded["offers"] == {"price": "5800", "priceCurrency": "JPY"}
    assert decoded["count"] == 3
    assert decoded["flag"] is True
    assert decoded["missing"] is None


def test_extract_json_ld_decodes_entities_in_script_content():
    html = """
    <html><head>
    <script type="application/ld+json">
    {"@type": "Product", "name": "Rikka Takarada &amp; Akane Shinjo feat. toridamono",
     "brand": {"@type": "Brand", "name": "Good Smile &amp; Company"}}
    </script>
    </head><body></body></html>
    """
    soup = BeautifulSoup(html, "lxml")
    blocks = extract_json_ld(soup)
    assert len(blocks) == 1
    assert blocks[0]["name"] == "Rikka Takarada & Akane Shinjo feat. toridamono"
    assert blocks[0]["brand"]["name"] == "Good Smile & Company"


def test_extract_common_decodes_json_ld_derived_name():
    html = """
    <html><head>
    <script type="application/ld+json">
    {"@type": "Product", "name": "A &amp; B Figure"}
    </script>
    </head><body></body></html>
    """
    common = extract_common(html, "https://example.com/p/1")
    assert common["name"] == "A & B Figure"


def test_figure_adapter_end_to_end_matches_reported_bug():
    """Reproduces the exact production bug: entity.name must be the decoded
    "Rikka Takarada & Akane Shinjo feat. toridamono", not the raw
    "Rikka Takarada &amp; Akane Shinjo feat. toridamono" that was stored.
    """
    html = """
    <html><head>
    <title>Rikka &amp; Akane | Good Smile Company</title>
    <link rel="canonical" href="https://www.goodsmile.com/en/product/1141716/x">
    <script type="application/ld+json">
    {"@context": "https://schema.org", "@type": "Product",
     "name": "Rikka Takarada &amp; Akane Shinjo feat. toridamono",
     "brand": {"@type": "Brand", "name": "Good Smile Company"},
     "sku": "GSC-1141716",
     "offers": {"@type": "Offer", "price": "23800", "priceCurrency": "JPY"}}
    </script>
    </head><body><h1>Rikka Takarada &amp; Akane Shinjo feat. toridamono</h1></body></html>
    """
    adapter = get_adapter("figure_official_site")
    common = extract_common(html, "https://www.goodsmile.com/en/product/1141716/x")
    record = adapter.extract(common, "https://www.goodsmile.com/en/product/1141716/x", html)

    assert record.name == "Rikka Takarada & Akane Shinjo feat. toridamono"
    assert "&amp;" not in record.name
