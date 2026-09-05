"""Adapter tests for lovehotel_couples (全国ラブホテル施設DB, Phase 1).

Fixtures under tests/fixtures/couples_*.html are reconstructions -- this
environment has no outbound web access to couples.jp (confirmed blocked;
see docs/lovehotel_couples_db.md). Covers: facility-vs-listing
classification (JSON-LD / postal-address / facility-ID signals), plain-text
address fallback when no structured data exists, prefecture/city
extraction, facility ID extraction, official-site link extraction (present
and absent), operating-status detection (explicit closed marker only,
never guessed "open"), missing-name -> review, malformed page handling, and
dedup fingerprinting via facility ID.
"""

from __future__ import annotations

from pathlib import Path

from db_collector_os.adapters import get_adapter, list_adapters
from db_collector_os.deduplication import compute_fingerprint
from db_collector_os.extraction.common import extract_common

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


def test_adapter_is_registered():
    assert "lovehotel_couples" in list_adapters()
    adapter = get_adapter("lovehotel_couples")
    assert adapter.entity_type == "love_hotel"
    assert adapter.required_fields == ("name",)


def test_facility_with_json_ld_extracts_full_record():
    html = load_fixture("couples_facility_detail_full.html")
    url = "https://couples.jp/hotel-details/12345/"
    adapter = get_adapter("lovehotel_couples")
    common = extract_common(html, url)
    record = adapter.extract(common, url, html)

    assert record.skip is False
    assert not record.missing_required
    assert record.name == "ホテル アルファ"
    assert record.entity_type == "love_hotel"
    assert record.canonical_url == url
    assert record.external_id == "12345"
    assert record.telephone == "03-1111-2222"
    assert record.fields["prefecture"] == "東京都"
    assert record.fields["city"] == "渋谷区"
    assert record.fields["official_url"] == "https://alpha-hotel.example.com/"
    assert record.fields["operating_status"] is None  # no closed marker -> unknown, never assumed "open"
    assert record.fields["source_name"] == "Couples"
    assert record.fields["source_facility_id"] == "12345"
    assert record.confidence == 0.75  # JSON-LD business block present -> higher confidence


def test_facility_without_json_ld_falls_back_to_text_address_and_url_id():
    html = load_fixture("couples_facility_detail_no_jsonld.html")
    url = "https://couples.jp/hotel-details/34567/"
    adapter = get_adapter("lovehotel_couples")
    common = extract_common(html, url)
    record = adapter.extract(common, url, html)

    assert record.skip is False
    assert record.name == "ホテル ガンマ"
    assert record.external_id == "34567"
    assert "530-0001" in record.address
    assert record.fields["prefecture"] == "大阪府"
    assert record.fields["city"] == "大阪市"
    assert record.fields["official_url"] == "https://gamma-hotel.example.com/top"
    assert record.confidence == 0.55  # no JSON-LD business block -> lower confidence


def test_missing_official_url_is_none_not_guessed():
    html = load_fixture("couples_facility_detail_no_official_url.html")
    url = "https://couples.jp/hotel-details/45678/"
    adapter = get_adapter("lovehotel_couples")
    common = extract_common(html, url)
    record = adapter.extract(common, url, html)

    assert record.skip is False
    assert record.name == "ホテル デルタ"
    assert record.fields["official_url"] is None
    assert record.fields["prefecture"] == "北海道"


def test_explicit_closed_marker_sets_operating_status_closed():
    html = load_fixture("couples_facility_detail_closed.html")
    url = "https://couples.jp/hotel-details/56789/"
    adapter = get_adapter("lovehotel_couples")
    common = extract_common(html, url)
    record = adapter.extract(common, url, html)

    assert record.fields["operating_status"] == "closed"
    assert record.fields["prefecture"] == "福岡県"


def test_missing_name_on_a_genuine_facility_page_goes_to_review_not_skip():
    """Postal address + facility ID present -> definitely a facility page,
    but no extractable name -> a real data-quality problem worth review,
    NOT a silent skip (see ExtractedRecord.missing_required vs .skip)."""
    html = load_fixture("couples_facility_detail_missing_name.html")
    url = "https://couples.jp/hotel-details/67890/"
    adapter = get_adapter("lovehotel_couples")
    common = extract_common(html, url)
    record = adapter.extract(common, url, html)

    assert record.skip is False
    assert record.missing_required == ["name"]
    assert record.external_id == "67890"


def test_area_list_page_is_skipped_not_reviewed():
    html = load_fixture("couples_area_list.html")
    url = "https://couples.jp/tokyo/"
    adapter = get_adapter("lovehotel_couples")
    common = extract_common(html, url)
    record = adapter.extract(common, url, html)

    assert record.skip is True
    assert not record.missing_required


def test_empty_area_list_page_is_skipped_without_crash():
    html = load_fixture("couples_area_list_empty.html")
    url = "https://couples.jp/okinawa/"
    adapter = get_adapter("lovehotel_couples")
    common = extract_common(html, url)
    record = adapter.extract(common, url, html)

    assert record.skip is True


def test_malformed_page_is_skipped_gracefully_not_crash():
    html = load_fixture("couples_malformed.html")
    url = "https://couples.jp/error-page"
    adapter = get_adapter("lovehotel_couples")
    common = extract_common(html, url)  # must not raise despite broken JSON-LD
    record = adapter.extract(common, url, html)

    assert record.skip is True


def test_facility_id_and_fingerprint_shared_across_different_urls_for_same_facility():
    """Same facility ID reached via two different URLs (tracking query
    string vs. clean path) must fingerprint identically, so the
    Deduplicator merges them into one entity rather than creating two."""
    html = load_fixture("couples_facility_detail_full.html")
    adapter = get_adapter("lovehotel_couples")

    url1 = "https://couples.jp/hotel-details/12345/"
    common1 = extract_common(html, url1)
    record1 = adapter.extract(common1, url1, html)

    url2 = "https://couples.jp/hotel-details/12345/?utm_source=list"
    common2 = extract_common(html, url2)
    record2 = adapter.extract(common2, url2, html)

    assert record1.external_id == record2.external_id == "12345"
    fp1 = compute_fingerprint(record1.entity_type, external_id=record1.external_id)
    fp2 = compute_fingerprint(record2.entity_type, external_id=record2.external_id)
    assert fp1 == fp2


def test_same_name_different_facility_extracts_as_a_distinct_record():
    """couples_facility_detail_conflict.html deliberately shares its exact
    name with couples_facility_detail_full.html but is a different
    real-world facility (different facility ID/prefecture/address) -- at
    the adapter level each must extract independently and correctly; the
    Deduplicator (exercised in test_lovehotel_couples_pipeline_integration.py)
    is what keeps these from being auto-merged."""
    html = load_fixture("couples_facility_detail_conflict.html")
    url = "https://couples.jp/hotel-details/99999/"
    adapter = get_adapter("lovehotel_couples")
    common = extract_common(html, url)
    record = adapter.extract(common, url, html)

    assert record.skip is False
    assert record.name == "ホテル アルファ"
    assert record.external_id == "99999"
    assert record.fields["prefecture"] == "神奈川県"
    assert "横浜市" in (record.fields["city"] or "")


def test_prefecture_and_city_never_guessed_when_address_missing():
    adapter = get_adapter("lovehotel_couples")
    html = """
    <html><head><meta charset="utf-8"><title>No Address Facility</title>
    <link rel="canonical" href="https://couples.jp/hotel-details/11122/"></head>
    <body><h1>ホテル 住所不明</h1></body></html>
    """
    url = "https://couples.jp/hotel-details/11122/"
    common = extract_common(html, url)
    record = adapter.extract(common, url, html)

    # facility ID alone (no postal address, no JSON-LD) is still a strong
    # enough signal to treat this as a facility page, but prefecture/city
    # must stay None rather than being guessed from nothing.
    assert record.skip is False
    assert record.fields["prefecture"] is None
    assert record.fields["city"] is None
