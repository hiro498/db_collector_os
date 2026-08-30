"""Production adapter: 全国ラブホテル施設DB (nationwide love hotel facility DB)
-- the SECOND production DB for DB Collector OS, after 美少女フィギュア公式
メーカーDB (see docs/first_production_db.md).

Design notes (see docs/lovehotel_couples_db.md for the full rationale):

- Primary source: カップルズ (couples.jp), a nationwide love-hotel directory.
  This targets `collector_type: local_business`, the same generic
  storefront/venue collector type `sample_local_business` already validated
  -- no schema.org guarantee here (unlike the figure DB's schema.org
  `Product` JSON-LD), so this adapter also falls back to plain visible text
  (a "〒nnn-nnnn ..." postal-code-shaped address near the page body) when no
  structured data is present, in addition to `extract_common`'s existing
  JSON-LD-based name/address/telephone extraction.
- Phase 1 priority is nationwide population formation (facility name /
  prefecture / city / address / detail URL / official URL / operating
  status / source facility ID), NOT deep attributes (price, rooms, plans,
  reviews) -- see class docstring below and the job's `required_fields`.
- This authoring environment has no outbound web access to couples.jp
  (confirmed: the agent network proxy rejects the CONNECT to couples.jp:443
  with a policy 403), so -- exactly like the first production DB's Good
  Smile job -- no URL pattern, pagination scheme, or HTML structure below
  is guessed as verified fact. Classification of "this is a facility detail
  page" relies only on generically-observable signals: a schema.org
  LodgingBusiness/Hotel/LocalBusiness JSON-LD block, OR a postal-code-
  shaped address string found in the page's own visible text, OR a numeric
  facility ID captured from the page's own canonical URL. A page with none
  of those is treated as a confirmed non-entity page (area/prefecture
  listing, nav, footer, ...) and skipped silently, the same
  `ExtractedRecord.skip` contract `figure_official_site` uses for listing
  pages. See docs/lovehotel_couples_db.md for why discovery deliberately
  does not scope `internal_links` to a guessed facility-URL regex.
- Official site URLs found on a facility's Couples page are captured into
  `fields.official_url` (with evidence) but are NEVER auto-enqueued into
  this job's own fetch_queue -- Phase 1 must never grow into
  "Couples -> official site -> whatever THAT page links to -> ...". See
  the production job YAML: `discovery.related_entities` is off, and
  `discovery.allowed_domains` only ever contains couples.jp hosts, so an
  official-site domain can never enter this job's fetch_queue at all.
- `source_facility_id` (this adapter's best-effort numeric-ID extraction
  from the page's own URL) is used as `ExtractedRecord.external_id`, the
  Deduplicator's strongest fingerprint signal (see
  `deduplication/fingerprint.py`) -- two different URLs (different query
  string, different slug) for the same facility ID collapse into one
  entity. `source_name` ("Couples") is recorded in `fields` on every
  record so a future second source for this same DB (e.g. an official-site
  backfill job) can tell which rows came from which source.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from ..discovery.prefecture import PREFECTURES
from .base import Adapter, ExtractedRecord
from .registry import register_adapter

SOURCE_NAME = "Couples"

_BUSINESS_TYPES = {"LodgingBusiness", "Hotel", "LocalBusiness"}

# Best-effort, not a confirmed Couples URL scheme (see module docstring):
# a run of 3+ digits in the URL PATH (never the query string) is treated as
# a candidate facility ID, e.g. ".../hotel/12345/" -> "12345". Overridable
# per job via config_json.discovery.facility_id_pattern once real HTTP
# access confirms the actual scheme, without needing an adapter change.
_DEFAULT_FACILITY_ID_RE = re.compile(r"/(\d{3,})(?:[/?]|$)")

# A postal code is a strong, low-false-positive signal that a page is
# describing one specific physical facility (as opposed to a prefecture/
# area listing page, which conventionally does not print a postal code per
# listed item). "〒" is optional since some sites omit the glyph.
_POSTAL_ADDRESS_RE = re.compile(r"〒?\s*(\d{3}-\d{4})\s*([^\n\r]{0,60})")

_CITY_RE = re.compile(r"^(.+?郡.+?[町村]|.+?[市区町村])")

_OFFICIAL_LINK_TEXT_RE = re.compile(r"公式|オフィシャル|ホームページ|official", re.IGNORECASE)
_AGGREGATOR_HOSTS = {"couples.jp", "www.couples.jp"}
_NON_OFFICIAL_HOST_MARKERS = (
    "twitter.com", "x.com", "instagram.com", "facebook.com", "youtube.com",
    "tiktok.com", "line.me", "maps.google.com", "google.com", "goo.gl",
)

# Explicit, unambiguous "this facility is no longer operating" text markers
# only -- STEP 5 of this DB's brief is explicit that operating status must
# never be guessed; the absence of a closed marker means "unknown", not
# "open" (see `fields.operating_status` being None, not "open", by default).
_CLOSED_MARKERS = ("閉店", "閉業", "廃業", "移転しました", "営業を終了")


@register_adapter("lovehotel_couples")
class LoveHotelCouplesAdapter(Adapter):
    """全国ラブホテル施設DB Phase 1: population formation only (name/
    prefecture/city/address/detail URL/official URL/operating status/
    source facility ID) -- deep attributes (price/rooms/plans/reviews) are
    explicitly out of scope for this adapter, see docs/lovehotel_couples_db.md.
    """

    name = "lovehotel_couples"
    entity_type = "love_hotel"
    required_fields = ("name",)

    def extract(self, common: dict[str, Any], url: str, raw_html: str | None) -> ExtractedRecord:
        json_ld_blocks = common.get("json_ld", []) or []
        business_block = _find_business_block(json_ld_blocks)

        name = common.get("name")
        address = common.get("address") or _extract_address_from_text(raw_html)

        canonical_url = common.get("canonical_url") or url
        facility_id = _extract_facility_id(canonical_url, url)

        has_postal_signal = bool(address and _POSTAL_ADDRESS_RE.search(address))
        is_facility_page = business_block is not None or has_postal_signal or bool(facility_id)

        if not is_facility_page:
            # No business structured data, no postal-code-shaped address, and
            # no facility ID in the URL -- almost certainly a prefecture/area
            # listing, pagination hub, or nav/footer page reached via
            # internal-link discovery, not a facility itself.
            return ExtractedRecord(
                skip=True, skip_reason="no LodgingBusiness/Hotel signal, postal address, or facility ID on page",
            )

        prefecture, city = _split_prefecture_city(address)
        official_url = _extract_official_url(raw_html or "", canonical_url)
        operating_status = _extract_operating_status(raw_html or "")

        record = ExtractedRecord(
            name=name,
            entity_type=self.entity_type,
            canonical_url=canonical_url,
            address=address,
            telephone=common.get("telephone"),
            external_id=facility_id,
            confidence=0.75 if business_block else 0.55,
            fields={
                "prefecture": prefecture,
                "city": city,
                "official_url": official_url,
                "operating_status": operating_status,
                "source_name": SOURCE_NAME,
                "source_facility_id": facility_id,
            },
        )
        if not record.name:
            record.missing_required = ["name"]
        return record


def _find_business_block(blocks: list[dict[str, Any]]) -> dict[str, Any] | None:
    for block in blocks:
        if _types(block) & _BUSINESS_TYPES:
            return block
    return None


def _types(block: dict[str, Any]) -> set[str]:
    t = block.get("@type")
    if isinstance(t, list):
        return set(t)
    return {t} if t else set()


def _extract_facility_id(canonical_url: str | None, url: str) -> str | None:
    for candidate in (canonical_url, url):
        if not candidate:
            continue
        path = urlsplit(candidate).path
        match = _DEFAULT_FACILITY_ID_RE.search(path)
        if match:
            return match.group(1)
    return None


def _extract_address_from_text(raw_html: str | None) -> str | None:
    """Fallback for pages without JSON-LD address: a postal-code-shaped
    string found in the page's own visible text (see module docstring for
    why this is a deliberately conservative, non-guessed signal).
    """
    if not raw_html:
        return None
    soup = BeautifulSoup(raw_html, "lxml")
    text = soup.get_text("\n")
    match = _POSTAL_ADDRESS_RE.search(text)
    if not match:
        return None
    postal, rest = match.group(1), " ".join(match.group(2).split())
    return f"〒{postal} {rest}".strip() if rest else f"〒{postal}"


def _split_prefecture_city(address: str | None) -> tuple[str | None, str | None]:
    """Extract prefecture/city ONLY when the exact, full prefecture name
    (with its legal suffix -- 都/道/府/県) is literally present in the
    address text; never inferred/guessed when it isn't (STEP 5: unknown
    items stay NULL rather than being filled in by best guess).
    """
    if not address:
        return None, None
    for pref in PREFECTURES:
        idx = address.find(pref)
        if idx == -1:
            continue
        remainder = address[idx + len(pref):].lstrip(" 　,、")
        match = _CITY_RE.match(remainder)
        city = match.group(1) if match else None
        return pref, city
    return None, None


def _extract_official_url(raw_html: str, page_url: str) -> str | None:
    if not raw_html:
        return None
    soup = BeautifulSoup(raw_html, "lxml")
    page_host = urlsplit(page_url).netloc.lower()
    for a in soup.find_all("a", href=True):
        link_text = a.get_text(strip=True) or ""
        if not _OFFICIAL_LINK_TEXT_RE.search(link_text):
            continue
        href = a["href"]
        if not href.startswith(("http://", "https://")):
            continue
        host = urlsplit(href).netloc.lower()
        if not host or host == page_host or host in _AGGREGATOR_HOSTS:
            continue
        if any(marker in host for marker in _NON_OFFICIAL_HOST_MARKERS):
            continue
        return href
    return None


def _extract_operating_status(raw_html: str) -> str | None:
    """Only ever returns "closed" (an explicit textual marker was found) or
    None ("unknown" -- never assumed to be "open" just because no closed
    marker was found; see STEP 5 of docs/lovehotel_couples_db.md).
    """
    if not raw_html:
        return None
    soup = BeautifulSoup(raw_html, "lxml")
    text = soup.get_text(" ")
    for marker in _CLOSED_MARKERS:
        if marker in text:
            return "closed"
    return None
