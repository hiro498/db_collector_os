from __future__ import annotations

import json
from pathlib import Path

from db_collector_os.adapters import get_adapter
from db_collector_os.extraction.common import extract_common

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


def test_official_site_adapter_extracts_product():
    html = load_fixture("official_site_product.html")
    adapter = get_adapter("sample_official_site")
    common = extract_common(html, "https://tires.example.com/products/super-tire-x")
    record = adapter.extract(common, "https://tires.example.com/products/super-tire-x", html)
    assert record.name == "Super Tire X"
    assert record.fields["brand"] == "Acme"
    assert record.fields["sku"] == "TIRE-X-001"
    assert record.fields["price"] == "128.50"
    assert not record.missing_required


def test_local_business_adapter_extracts_address_and_phone():
    html = load_fixture("local_business.html")
    adapter = get_adapter("sample_local_business")
    common = extract_common(html, "https://directory.example.com/shops/fortune-house-sakura")
    record = adapter.extract(common, "https://directory.example.com/shops/fortune-house-sakura", html)
    assert record.name == "占い館 桜"
    assert "神宮前" in record.address
    assert record.telephone == "03-1234-5678"
    assert not record.missing_required


def test_person_adapter_extracts_social_links():
    html = load_fixture("person.html")
    adapter = get_adapter("sample_person")
    common = extract_common(html, "https://profiles.example.com/people/hana-suzuki")
    record = adapter.extract(common, "https://profiles.example.com/people/hana-suzuki", html)
    assert record.name == "Hana Suzuki"
    assert record.fields["job_title"] == "Fortune Teller"
    assert "https://twitter.com/hana_suzuki" in record.fields["social_urls"]


def test_api_adapter_parses_item_list():
    payload = json.loads(load_fixture("api_products.json"))
    adapter = get_adapter("sample_api")
    records = adapter.parse_api(payload, "https://api.example.com/v1/products")
    assert len(records) == 2
    assert records[0].name == "Widget Alpha"
    assert records[0].external_id == "P-001"
    assert not records[0].missing_required


def test_adapter_flags_missing_required_field():
    adapter = get_adapter("sample_local_business")
    common = extract_common("<html><head><title>No structured data</title></head><body>hi</body></html>", "https://example.com/x")
    record = adapter.extract(common, "https://example.com/x", "")
    assert "address" in record.missing_required
