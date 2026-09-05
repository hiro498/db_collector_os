"""Couples (couples.jp) Nationwide Facility Discovery -- a dedicated,
couples.jp-specific discovery module for the 全国ラブホテル施設DB
(job_prod_lovehotel_couples). See docs/lovehotel_couples_db.md.

Why this module exists (as opposed to the generic domain-scoped
`discovery/internal_links.py` this job's `config_json.discovery` already
uses): the earlier revision of this job could not confirm couples.jp's real
facility-URL scheme from its authoring environment (no outbound network
access), so it deliberately crawled every same-domain link and left "is
this actually a facility" entirely to the adapter's own (necessarily
generic/loose) content heuristics. That is why a production audit found the
job's `entities` table mostly full of non-facility pages (area/prefecture
listings, articles, ...) misclassified or crawled in bulk, with genuine
facility rows a small minority.

This module is given a CONFIRMED real fact this codebase did not previously
have: a real facility detail page is

    https://couples.jp/hotel-details/{numeric_id}

(example: https://couples.jp/hotel-details/1238) and

    /prefectures/, /articles/, /themes/, /movies, /hotel-groups, /users/

are confirmed NOT facility pages. This lets discovery be built around a
real, verifiable facility-URL shape instead of "any same-domain page",
without needing to guess the (still-unconfirmed) prefecture/city/pagination
navigation URL scheme -- `is_couples_listing_or_navigation_url` stays a
broad, denylist-based "safe to keep crawling" test (same-host, not one of
the confirmed-non-facility content silos) rather than an allowlist of a
guessed nav URL shape, so this module can still traverse whatever real
navigation structure couples.jp actually uses.

This module performs NO HTTP itself except through a caller-supplied
fetch_engine (anything exposing `.fetch(url) -> object` with `.ok`/
`.content`/`.final_url`, matching `fetching.client.FetchEngine` -- see
`FixtureFetchEngine` below for an offline stand-in used by tests and by
`db-collector couples discover-dry-run --fixtures-dir`). It never writes to
any database and never enqueues anything into a job's real fetch_queue --
see `db_collector_os/cli.py`'s `couples discover-dry-run` command for the
read-only nationwide dry-run this module is designed to support.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urljoin, urlsplit, urldefrag

from bs4 import BeautifulSoup

from ..normalization import normalize_url
from .prefecture import PREFECTURES, PREFECTURE_SLUGS

# The only two hosts a canonical Couples facility URL is ever recognized
# under -- www and apex are the same site (canonical form always drops
# "www.", see canonicalize_couples_facility_url).
_ALLOWED_HOSTS = {"couples.jp", "www.couples.jp"}

# Confirmed real facility detail URL shape (given directly in this DB's
# brief, along with the worked example https://couples.jp/hotel-details/1238).
# Trailing sub-paths (/review, /rooms, /coupon, /plan, ...) and a trailing
# slash are all part of the SAME facility and must canonicalize together.
_FACILITY_PATH_RE = re.compile(r"^/hotel-details/(\d+)(?:/.*)?$")

# Confirmed NOT facility pages (given directly in this DB's brief). Kept as
# a denylist, not the only excluded content, so a same-host page that is
# neither a facility nor one of these is still treated as navigable by
# default -- couples.jp's real prefecture/city/pagination URL scheme is
# still not independently confirmed from this authoring environment (see
# module docstring), and an allowlist risks silently killing the crawl the
# same way the previous revision's docs warned against.
_EXCLUDED_CONTENT_PREFIXES = (
    "/articles",
    "/themes",
    "/movies",
    "/hotel-groups",
    "/users",
)

_SKIP_HREF_PREFIXES = ("javascript:", "mailto:", "tel:", "#")


def _host_allowed(netloc: str) -> bool:
    """Empty netloc means a relative link already resolved against an
    allowed base URL by the caller -- treated as allowed. A non-empty
    netloc must be exactly one of the two known Couples hosts."""
    return not netloc or netloc.lower() in _ALLOWED_HOSTS


def canonicalize_couples_facility_url(url: str | None) -> str | None:
    """Collapse any real or derived Couples facility URL to one canonical
    form, or return None if `url` is not a Couples facility URL at all.

    https://couples.jp/hotel-details/1238            -> https://couples.jp/hotel-details/1238
    https://www.couples.jp/hotel-details/1238        -> https://couples.jp/hotel-details/1238
    https://couples.jp/hotel-details/1238/           -> https://couples.jp/hotel-details/1238
    https://couples.jp/hotel-details/1238?foo=bar    -> https://couples.jp/hotel-details/1238
    https://couples.jp/hotel-details/1238#abc        -> https://couples.jp/hotel-details/1238
    https://couples.jp/hotel-details/1238/review     -> https://couples.jp/hotel-details/1238
    https://couples.jp/hotel-details/1238/rooms      -> https://couples.jp/hotel-details/1238
    https://couples.jp/hotel-details/1238/coupon     -> https://couples.jp/hotel-details/1238
    https://couples.jp/hotel-details/1238/plan       -> https://couples.jp/hotel-details/1238

    Facility identity is the numeric hotel id alone -- a non-numeric id (a
    slug, a UUID, ...) never matches and returns None.
    """
    if not url:
        return None
    stripped, _fragment = urldefrag(url.strip())
    parts = urlsplit(stripped)
    if not _host_allowed(parts.netloc):
        return None
    match = _FACILITY_PATH_RE.match(parts.path or "")
    if not match:
        return None
    return f"https://couples.jp/hotel-details/{match.group(1)}"


def is_couples_facility_url(url: str | None) -> bool:
    """True for a facility detail URL OR any of its derived sub-paths
    (/review, /rooms, /coupon, /plan, ...) -- i.e. anything
    `canonicalize_couples_facility_url` can resolve to a facility id."""
    return canonicalize_couples_facility_url(url) is not None


def is_couples_listing_or_navigation_url(url: str | None) -> bool:
    """True for a same-host Couples URL that is safe to keep crawling for
    further links (a prefecture/area/search/pagination page) -- i.e.
    same-host, NOT itself a facility URL, and not one of the confirmed
    non-facility content silos (/articles, /themes, /movies, /hotel-groups,
    /users) this DB's brief says must never be mistaken for navigation
    toward facilities. `/prefectures/` is deliberately NOT excluded here --
    it is this DB's confirmed prefecture entry-point path (see
    `discover_all_prefectures`)."""
    if not url:
        return False
    parts = urlsplit(url)
    if not _host_allowed(parts.netloc):
        return False
    path = parts.path or "/"
    if _FACILITY_PATH_RE.match(path):
        return False
    return not any(path == p or path.startswith(p + "/") for p in _EXCLUDED_CONTENT_PREFIXES)


def _iter_link_hrefs(html: str | None, base_url: str) -> list[str]:
    """Every `<a href>` on the page, resolved to an absolute URL against
    `base_url`, skipping non-navigable schemes (javascript:/mailto:/tel:)
    and bare in-page anchors. Never raises on malformed HTML -- BeautifulSoup
    with lxml degrades gracefully, matching the rest of this codebase's
    "a broken page must never crash discovery" contract."""
    if not html:
        return []
    soup = BeautifulSoup(html, "lxml")
    hrefs = []
    for a in soup.find_all("a", href=True):
        href = (a["href"] or "").strip()
        if not href or href.startswith(_SKIP_HREF_PREFIXES):
            continue
        hrefs.append(urljoin(base_url, href))
    return hrefs


def extract_couples_facility_urls(html: str | None, base_url: str) -> list[str]:
    """Every DISTINCT canonical facility URL linked from this page (order
    preserved, first occurrence wins) -- review/rooms/coupon/plan and other
    derived links are already folded into their canonical
    `/hotel-details/{id}` form, so this list never contains a non-canonical
    facility URL."""
    seen: dict[str, None] = {}
    for absolute in _iter_link_hrefs(html, base_url):
        canonical = canonicalize_couples_facility_url(absolute)
        if canonical is not None:
            seen.setdefault(canonical, None)
    return list(seen.keys())


def count_raw_facility_hrefs(html: str | None, base_url: str) -> int:
    """Every raw `<a href>` occurrence that points at a facility URL
    (including repeats and derived /review, /rooms, ... links, BEFORE
    canonicalization/dedup) -- used only for the RAW_FACILITY_URLS
    contamination/volume check in the nationwide dry-run report, not for
    building the actual facility result set (`extract_couples_facility_urls`
    is the one that matters there)."""
    return sum(1 for href in _iter_link_hrefs(html, base_url) if is_couples_facility_url(href))


def extract_navigation_urls(html: str | None, base_url: str) -> list[str]:
    """Every DISTINCT same-host, non-facility, non-excluded-content URL
    linked from this page (order preserved) -- prefecture/area/search-result
    pages and pagination links, the set `discover_prefecture_facilities`
    keeps following to reach every facility page reachable from one
    prefecture's entry point."""
    seen: dict[str, None] = {}
    for absolute in _iter_link_hrefs(html, base_url):
        if is_couples_listing_or_navigation_url(absolute):
            seen.setdefault(absolute, None)
    return list(seen.keys())


def extract_prefecture_entry_urls(html: str | None, base_url: str) -> dict[str, str]:
    """Map official prefecture name (`discovery.prefecture.PREFECTURES`,
    e.g. "東京都") -> absolute entry URL, for every anchor on this page
    whose VISIBLE TEXT is an exact prefecture name. This is how
    `discover_all_prefectures` finds each of the 47 prefectures' real
    Couples entry point without guessing a URL template: a nationwide
    directory conventionally exposes a persistent "prefecture list" nav
    widget naming every prefecture verbatim, on the top page and/or a
    dedicated `/prefectures/` index. A prefecture with no matching anchor on
    any of the given entry pages is simply absent from the returned dict --
    callers (see `discover_all_prefectures`) treat that as a genuine
    navigation failure for that prefecture, not a guessed URL."""
    if not html:
        return {}
    soup = BeautifulSoup(html, "lxml")
    found: dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        text = a.get_text(strip=True)
        if text not in _PREFECTURE_SET or text in found:
            continue
        href = (a["href"] or "").strip()
        if not href or href.startswith(_SKIP_HREF_PREFIXES):
            continue
        absolute, _fragment = urldefrag(urljoin(base_url, href))
        if not _host_allowed(urlsplit(absolute).netloc):
            continue
        found[text] = absolute
    return found


_PREFECTURE_SET = frozenset(PREFECTURES)


class FetchLike(Protocol):
    def fetch(self, url: str) -> Any: ...  # returns an object with .ok/.content/.final_url


@dataclass
class FacilityHit:
    """One discovered facility, with its provenance kept (task requirement
    #9: "発見元prefectureを保持できる設計にする")."""

    canonical_url: str
    facility_id: str
    prefecture: str
    discovered_from_url: str


@dataclass
class PrefectureDiscoveryResult:
    prefecture: str
    entry_url: str | None
    status: str = "ok"  # ok | empty | failed | no_entry_url
    error: str | None = None
    pages_visited: int = 0
    pages_failed: int = 0
    raw_facility_url_count: int = 0
    canonical_facility_url_count: int = 0
    facilities: list[FacilityHit] = field(default_factory=list)

    @property
    def unique_facility_ids(self) -> set[str]:
        return {f.facility_id for f in self.facilities}


@dataclass
class NationwideDiscoveryResult:
    prefectures: dict[str, PrefectureDiscoveryResult]
    index_pages_fetched: int = 0
    index_pages_failed: int = 0

    @property
    def visited_prefecture_count(self) -> int:
        return len(self.prefectures)

    @property
    def failed_prefectures(self) -> list[str]:
        return [p for p, r in self.prefectures.items() if r.status in ("failed", "no_entry_url")]

    @property
    def raw_facility_urls(self) -> int:
        return sum(r.raw_facility_url_count for r in self.prefectures.values())

    @property
    def canonical_facility_urls(self) -> int:
        return sum(r.canonical_facility_url_count for r in self.prefectures.values())

    def all_facilities(self) -> list[FacilityHit]:
        out: list[FacilityHit] = []
        for r in self.prefectures.values():
            out.extend(r.facilities)
        return out

    @property
    def unique_facility_ids(self) -> dict[str, FacilityHit]:
        """facility_id -> the FIRST FacilityHit seen for it (first-prefecture-wins)."""
        unique: dict[str, FacilityHit] = {}
        for hit in self.all_facilities():
            unique.setdefault(hit.facility_id, hit)
        return unique

    @property
    def duplicate_facility_id_count(self) -> int:
        return self.canonical_facility_urls - len(self.unique_facility_ids)

    @property
    def review_url_contamination(self) -> int:
        """Count of any surviving facility URL that is NOT the bare
        canonical form (i.e. canonicalization somehow failed to strip a
        derived /review, /rooms, /coupon, /plan suffix) -- must always be 0."""
        return sum(
            1 for hit in self.unique_facility_ids.values()
            if hit.canonical_url != f"https://couples.jp/hotel-details/{hit.facility_id}"
        )

    @property
    def non_facility_url_contamination(self) -> int:
        """Count of any surviving "facility" URL that does not actually
        match the confirmed facility URL shape at all -- must always be 0."""
        return sum(1 for hit in self.unique_facility_ids.values() if not is_couples_facility_url(hit.canonical_url))


def discover_prefecture_facilities(
    prefecture: str,
    entry_url: str | None,
    fetch_engine: FetchLike,
    max_pages: int = 50,
    rate_limit_seconds: float = 0.0,
) -> PrefectureDiscoveryResult:
    """Breadth-first crawl from one prefecture's navigation entry point,
    following only `is_couples_listing_or_navigation_url` links (area/city
    listings, search results, pagination -- whatever the real nav structure
    turns out to be), collecting every `/hotel-details/{id}` link found
    along the way. Bounded by `max_pages` (load control -- task requirement
    "負荷を抑えてください"); never invents a URL, never HTTP-probes a numeric
    ID range.

    Distinguishes three "found nothing" outcomes instead of collapsing them
    into one silent zero (task requirement: "0件県は自動的に成功扱いにせず、
    navigation failureなのか本当に0件なのか判別できるようにする"):
      - "no_entry_url": this prefecture's entry point was never found at all
        (a navigation failure at the index-page step).
      - "failed": an entry URL was found, but it and every page reached from
        it failed to fetch (a navigation failure at the crawl step).
      - "empty": pages were fetched successfully, but genuinely no facility
        link was ever found (a real zero, not a failure).
      - "ok": at least one facility was found.
    """
    result = PrefectureDiscoveryResult(prefecture=prefecture, entry_url=entry_url)
    if not entry_url:
        result.status = "no_entry_url"
        result.error = "no navigation entry URL discovered for this prefecture"
        return result

    visited: set[str] = set()
    queued: set[str] = {normalize_url(entry_url)}
    queue: list[str] = [entry_url]
    facility_ids_seen: dict[str, FacilityHit] = {}
    any_page_fetched_ok = False

    while queue and result.pages_visited < max_pages:
        url = queue.pop(0)
        key = normalize_url(url)
        if key in visited:
            continue
        visited.add(key)

        if rate_limit_seconds:
            time.sleep(rate_limit_seconds)
        fetch_result = fetch_engine.fetch(url)
        result.pages_visited += 1

        if not fetch_result or not getattr(fetch_result, "ok", False) or not getattr(fetch_result, "content", None):
            result.pages_failed += 1
            continue
        any_page_fetched_ok = True

        html = fetch_result.content
        page_url = getattr(fetch_result, "final_url", None) or url

        result.raw_facility_url_count += count_raw_facility_hrefs(html, page_url)
        for canonical in extract_couples_facility_urls(html, page_url):
            result.canonical_facility_url_count += 1
            facility_id = canonical.rsplit("/", 1)[-1]
            if facility_id not in facility_ids_seen:
                facility_ids_seen[facility_id] = FacilityHit(
                    canonical_url=canonical, facility_id=facility_id,
                    prefecture=prefecture, discovered_from_url=url,
                )

        if result.pages_visited < max_pages:
            for nav_url in extract_navigation_urls(html, page_url):
                nav_key = normalize_url(nav_url)
                if nav_key not in queued and nav_key not in visited:
                    queued.add(nav_key)
                    queue.append(nav_url)

    result.facilities = list(facility_ids_seen.values())
    if not any_page_fetched_ok:
        result.status = "failed"
        result.error = "entry URL and every page reached from it failed to fetch"
    elif not result.facilities:
        result.status = "empty"
    else:
        result.status = "ok"
    return result


def discover_all_prefectures(
    fetch_engine: FetchLike,
    index_urls: list[str] | None = None,
    max_pages_per_prefecture: int = 50,
    rate_limit_seconds: float = 0.0,
) -> NationwideDiscoveryResult:
    """Full nationwide discovery: find all 47 prefectures' entry URLs from
    `index_urls` (default: just the Couples top page), then run
    `discover_prefecture_facilities` for each of the 47 (task requirement
    #1/#2), in `discovery.prefecture.PREFECTURES` order (北海道...沖縄県) so
    every caller/report enumerates all 47 in a fixed, stable order --
    including prefectures for which no entry URL was ever found (they still
    get a `PrefectureDiscoveryResult(status="no_entry_url")` entry, never
    silently dropped from the result set)."""
    index_urls = index_urls or ["https://couples.jp/"]
    entry_urls: dict[str, str] = {}
    index_pages_fetched = 0
    index_pages_failed = 0

    for index_url in index_urls:
        if rate_limit_seconds:
            time.sleep(rate_limit_seconds)
        fetch_result = fetch_engine.fetch(index_url)
        if not fetch_result or not getattr(fetch_result, "ok", False) or not getattr(fetch_result, "content", None):
            index_pages_failed += 1
            continue
        index_pages_fetched += 1
        page_url = getattr(fetch_result, "final_url", None) or index_url
        for pref, url in extract_prefecture_entry_urls(fetch_result.content, page_url).items():
            entry_urls.setdefault(pref, url)

    prefectures: dict[str, PrefectureDiscoveryResult] = {}
    for pref in PREFECTURES:
        prefectures[pref] = discover_prefecture_facilities(
            pref, entry_urls.get(pref), fetch_engine,
            max_pages=max_pages_per_prefecture, rate_limit_seconds=rate_limit_seconds,
        )
    return NationwideDiscoveryResult(
        prefectures=prefectures, index_pages_fetched=index_pages_fetched, index_pages_failed=index_pages_failed,
    )


@dataclass
class SimpleFetchResult:
    url: str
    ok: bool
    content: str | None = None
    http_status: int | None = None
    final_url: str | None = None
    error: str | None = None


class FixtureFetchEngine:
    """A `fetch_engine`-compatible stand-in that serves HTML from local
    files instead of the network, keyed by a `manifest.json` (`{"<url>":
    "<relative html file path>"}`) inside `fixtures_dir`. Exercises the
    exact same discovery code path as a live `FetchEngine` -- used by this
    module's own tests, and by `db-collector couples discover-dry-run
    --fixtures-dir` for an environment (like this one) with no outbound
    network access to couples.jp, so the discovery algorithm can still be
    verified end-to-end without guessing at what a live response would be.
    A URL missing from the manifest is reported as a simulated 404, the
    same "this page failed to fetch" outcome a real 404 would produce.
    """

    def __init__(self, fixtures_dir: str | Path):
        self.fixtures_dir = Path(fixtures_dir)
        manifest_path = self.fixtures_dir / "manifest.json"
        if manifest_path.exists():
            self._manifest: dict[str, str] = json.loads(manifest_path.read_text(encoding="utf-8"))
        else:
            self._manifest = {}

    def fetch(self, url: str) -> SimpleFetchResult:
        filename = self._manifest.get(url) or self._manifest.get(normalize_url(url))
        if not filename:
            return SimpleFetchResult(url=url, ok=False, http_status=404, error="not in fixture manifest (simulated 404)")
        path = self.fixtures_dir / filename
        if not path.exists():
            return SimpleFetchResult(url=url, ok=False, http_status=404, error=f"fixture file missing: {filename}")
        return SimpleFetchResult(url=url, ok=True, http_status=200, final_url=url, content=path.read_text(encoding="utf-8"))


_REPORT_LABEL_WIDTH = 2


def format_dry_run_report(result: NationwideDiscoveryResult, *, simulated: bool) -> str:
    """The exact report format specified for the nationwide dry-run (task
    "第二段階" / "Gate"), as plain text. `simulated=True` prepends a banner
    making clear the run used `FixtureFetchEngine` / local test data rather
    than a live fetch against couples.jp -- see `NEXT` in the final task
    report for why this session could not produce a live-network run."""
    lines: list[str] = []
    if simulated:
        lines.append("# SIMULATED RUN -- FixtureFetchEngine (no live network access to couples.jp from this")
        lines.append("# session/environment; see docs/lovehotel_couples_db.md). NOT production counts.")
        lines.append("")

    lines.append(f"47_PREFECTURES_VISITED={result.visited_prefecture_count}")
    lines.append(f"FAILED_PREFECTURES={len(result.failed_prefectures)}")
    lines.append("")

    for i, (pref, slug) in enumerate(zip(PREFECTURES, PREFECTURE_SLUGS), start=1):
        r = result.prefectures.get(pref)
        label = f"PREFECTURE_{i:0{_REPORT_LABEL_WIDTH}d}_{slug.upper()}"
        if r is None:
            lines.append(f"{label}=NOT_VISITED")
        elif r.status in ("failed", "no_entry_url"):
            lines.append(f"{label}=FAILED({r.status}: {r.error})")
        else:
            lines.append(f"{label}={len(r.unique_facility_ids)} (status={r.status})")

    lines.append("")
    lines.append(f"RAW_FACILITY_URLS={result.raw_facility_urls}")
    lines.append(f"CANONICAL_FACILITY_URLS={result.canonical_facility_urls}")
    lines.append(f"UNIQUE_FACILITY_IDS={len(result.unique_facility_ids)}")
    lines.append("")
    lines.append(f"DUPLICATE_FACILITY_IDS={result.duplicate_facility_id_count}")
    lines.append(f"REVIEW_URL_CONTAMINATION={result.review_url_contamination}")
    lines.append(f"NON_FACILITY_URL_CONTAMINATION={result.non_facility_url_contamination}")
    lines.append("")
    lines.append(f"FAILED_PREFECTURES={len(result.failed_prefectures)}")
    lines.append("")
    lines.append(f"DISCOVERY_COMPLETE={'YES' if not result.failed_prefectures else 'NO'}")
    return "\n".join(lines) + "\n"


def to_json_summary(result: NationwideDiscoveryResult) -> dict[str, Any]:
    """Full machine-readable detail (every facility hit, with its
    discovered-from prefecture and source page) -- the JSON companion to
    `format_dry_run_report`'s plain-text summary."""
    return {
        "prefectures_visited": result.visited_prefecture_count,
        "failed_prefectures": result.failed_prefectures,
        "index_pages_fetched": result.index_pages_fetched,
        "index_pages_failed": result.index_pages_failed,
        "raw_facility_urls": result.raw_facility_urls,
        "canonical_facility_urls": result.canonical_facility_urls,
        "unique_facility_ids": len(result.unique_facility_ids),
        "duplicate_facility_ids": result.duplicate_facility_id_count,
        "review_url_contamination": result.review_url_contamination,
        "non_facility_url_contamination": result.non_facility_url_contamination,
        "per_prefecture": {
            pref: {
                "status": r.status,
                "error": r.error,
                "entry_url": r.entry_url,
                "pages_visited": r.pages_visited,
                "pages_failed": r.pages_failed,
                "raw_facility_url_count": r.raw_facility_url_count,
                "canonical_facility_url_count": r.canonical_facility_url_count,
                "unique_facility_count": len(r.unique_facility_ids),
                "facility_ids": sorted(r.unique_facility_ids, key=int),
            }
            for pref, r in result.prefectures.items()
        },
        "facilities": [
            {
                "facility_id": hit.facility_id,
                "canonical_url": hit.canonical_url,
                "prefecture": hit.prefecture,
                "discovered_from_url": hit.discovered_from_url,
            }
            for hit in result.unique_facility_ids.values()
        ],
    }
