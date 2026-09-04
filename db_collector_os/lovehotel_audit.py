"""全国ラブホテル施設DB (`job_prod_lovehotel_couples`) audit + summary.

Read-only. Every function here only ever SELECTs -- nothing in this module
writes to `entities`, `entity_candidates`, `fetch_queue`, `review_queue`, or
`jobs`. It exists so the Admin Dashboard (and the CLI) can both show the
real state of this DB without re-implementing the same classification logic
twice (see `db_collector_os/admin/app.py` and `cli.py`, both of which import
from here instead of duplicating any of this).

## Why entity counts alone are misleading

`entities` rows for this job are NOT all real, single-facility records.
`LoveHotelCouplesAdapter.extract()` (see `adapters/lovehotel_couples.py`
and `docs/lovehotel_couples_db.md`) treats a page as a facility page if
ANY of: a schema.org LodgingBusiness/Hotel/LocalBusiness JSON-LD block, a
postal-code-shaped address in the page's visible text, or a 3+ digit run
in the page's own URL path. The last two signals are deliberately
permissive (documented as best-effort, unverified against real couples.jp
HTML) and also fire on prefecture/area-listing pages reached via
`internal_links` discovery -- so a raw `COUNT(*) FROM entities` mixes real
facilities in with mis-accepted listing/homepage pages. Treating that raw
count as "有効施設数" (valid facility count) would overstate the DB's real
coverage by orders of magnitude.

## Classification signals used (nothing new, nothing guessed)

- `data_json.operating_status`: the adapter only ever writes `"closed"`
  (an explicit textual marker was found) or leaves it unset -- never
  `"open"` by assumption. A closed marker is the strongest available
  "this describes one real facility, that facility is no longer
  operating" signal, so it is checked first and reported as its own
  bucket (CLOSED), separate from currently-valid facilities.
- `canonical_url` path `""`/`"/"`: the site's own homepage, occasionally
  captured as if it were an entity (e.g. an official-site backlink that
  resolves back to the aggregator's own root).
- `evidence.confidence`: recorded at 0.75 when the adapter found a real
  JSON-LD business block, 0.55 when it fell back to the much more
  permissive postal-address/URL-ID signals (see
  `docs/lovehotel_couples_db.md` "Evidence" section). This is the only
  signal already persisted in the schema that distinguishes "this page
  really looked like one facility" from "this page merely matched one of
  the weak fallback signals" -- the JSON-LD block itself is never stored
  on the entity row, so this confidence value is the closest available
  proxy without re-fetching or re-parsing any page.
- presence of `address` / `data_json.prefecture` / `data_json.city`: an
  entity with a name but literally no location data at all is too
  little to classify as facility or listing either way.

None of the bucket sizes below are hardcoded -- they always come from a
live query against whatever database `db` points at.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from .candidates import CandidateStore
from .database import Database
from .discovery.prefecture import PREFECTURES
from .fetching import FetchQueue
from .models.enums import ReviewReason
from .review import ReviewQueue

LOVEHOTEL_JOB_ID = "job_prod_lovehotel_couples"
LOVEHOTEL_ADAPTER = "lovehotel_couples"
LOVEHOTEL_ENTITY_TYPE = "love_hotel"

PREFECTURE_TOTAL = len(PREFECTURES)

# Confidence the adapter records when a real JSON-LD business block was
# present (0.75) vs. its weaker postal-address/URL-id fallback (0.55) --
# see adapters/lovehotel_couples.py's `confidence=0.75 if business_block
# else 0.55`. Anything at or above this line is treated as a genuine,
# single-facility signal.
STRONG_SIGNAL_CONFIDENCE = 0.7


class LoveHotelCategory:
    """A strict partition: every entity for this job lands in exactly one
    of these, so the bucket counts always sum to the job's total entity
    count."""

    FACILITY = "facility"
    LISTING = "listing"
    HOMEPAGE = "homepage"
    CLOSED = "closed"
    INCOMPLETE = "incomplete"
    UNKNOWN = "unknown"

    ALL = (FACILITY, LISTING, HOMEPAGE, CLOSED, INCOMPLETE, UNKNOWN)

    # Categories that describe one real, physical facility (open or
    # closed) -- the set coverage/completeness math should be based on,
    # per the explicit requirement that mis-accepted LISTING/HOMEPAGE rows
    # must never inflate coverage denominators.
    REAL_FACILITY = (FACILITY, CLOSED)


def classify_entity(entity: dict[str, Any], max_confidence: float | None) -> str:
    """Classify one `entities` row (as returned by `EntityStore.get`/`list`,
    i.e. with a decoded `data` dict) plus the MAX(evidence.confidence) ever
    recorded for it.
    """
    data = entity.get("data") or {}

    if data.get("operating_status") == "closed":
        return LoveHotelCategory.CLOSED

    canonical_url = entity.get("canonical_url") or ""
    if canonical_url and urlsplit(canonical_url).path in ("", "/"):
        return LoveHotelCategory.HOMEPAGE

    has_location = bool(entity.get("address") or data.get("prefecture") or data.get("city"))

    if max_confidence is None:
        # No evidence at all for this entity -- can't tell anything about
        # how it was matched, so it can't be trusted as facility or
        # listing either way.
        return LoveHotelCategory.UNKNOWN
    if not has_location:
        return LoveHotelCategory.INCOMPLETE
    if max_confidence >= STRONG_SIGNAL_CONFIDENCE:
        return LoveHotelCategory.FACILITY
    return LoveHotelCategory.LISTING


def _entities_with_confidence(db: Database, job_id: str) -> list[dict[str, Any]]:
    """One query: every (non-deleted) entity for this job, decoded, plus the
    highest evidence confidence ever recorded for it. Bounded by this job's
    own entity count (thousands, not the candidate table's hundreds of
    thousands) -- safe to classify row-by-row in Python afterwards.
    """
    import json

    rows = db.query(
        """
        SELECT e.*, me.max_conf AS max_confidence
        FROM entities e
        LEFT JOIN (
            SELECT entity_id, MAX(confidence) AS max_conf FROM evidence GROUP BY entity_id
        ) me ON me.entity_id = e.entity_id
        WHERE e.job_id = ? AND e.deleted_at IS NULL
        """,
        (job_id,),
    )
    decoded = []
    for row in rows:
        row = dict(row)
        row["data"] = json.loads(row.pop("data_json") or "{}")
        decoded.append(row)
    return decoded


def classification_counts(db: Database, job_id: str = LOVEHOTEL_JOB_ID) -> dict[str, Any]:
    """Partition every entity for this job into `LoveHotelCategory` buckets.

    Returns bucket counts (always summing to `total`) plus the raw entity
    rows already sorted into their category, so callers needing more detail
    (e.g. coverage math below) don't have to re-run the classification.
    """
    entities = _entities_with_confidence(db, job_id)
    counts = {c: 0 for c in LoveHotelCategory.ALL}
    by_category: dict[str, list[dict[str, Any]]] = {c: [] for c in LoveHotelCategory.ALL}
    for row in entities:
        category = classify_entity(row, row.get("max_confidence"))
        counts[category] += 1
        by_category[category].append(row)
    return {"total": len(entities), "counts": counts, "by_category": by_category}


def coverage_summary(
    db: Database, job_id: str = LOVEHOTEL_JOB_ID, *, classification: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Nationwide coverage, computed ONLY over the real-facility set
    (FACILITY + CLOSED) -- mis-accepted LISTING/HOMEPAGE rows never count
    toward the denominator or numerator here, per the explicit requirement
    that they must not inflate coverage.

    `classification` lets a caller (e.g. `lovehotel_summary`) that already
    ran `classification_counts` pass it in, instead of this function
    re-querying and re-classifying every entity a second time.
    """
    classification = classification or classification_counts(db, job_id)
    real_rows: list[dict[str, Any]] = []
    for cat in LoveHotelCategory.REAL_FACILITY:
        real_rows.extend(classification["by_category"][cat])

    real_total = len(real_rows)
    prefectures_covered: set[str] = set()
    with_prefecture = 0
    with_city = 0
    for row in real_rows:
        data = row.get("data") or {}
        pref = data.get("prefecture")
        city = data.get("city")
        if pref:
            prefectures_covered.add(pref)
            with_prefecture += 1
        if city:
            with_city += 1

    prefecture_covered_count = len(prefectures_covered)
    return {
        "real_facility_total": real_total,
        "prefecture_covered_count": prefecture_covered_count,
        "prefecture_total": PREFECTURE_TOTAL,
        "prefecture_coverage_ratio": (prefecture_covered_count / PREFECTURE_TOTAL) if PREFECTURE_TOTAL else 0.0,
        "prefecture_info_rate": (with_prefecture / real_total) if real_total else 0.0,
        "city_info_rate": (with_city / real_total) if real_total else 0.0,
        "covered_prefectures": sorted(prefectures_covered),
    }


def collection_summary(db: Database, job_id: str = LOVEHOTEL_JOB_ID) -> dict[str, Any]:
    """Candidate + fetch-queue counts, both via a single `GROUP BY status`
    query each (`CandidateStore.counts_by_status` / `FetchQueue.stats`,
    reused as-is -- never a per-row scan of the 100k+-row candidate table).
    """
    candidate_counts = CandidateStore(db).counts_by_status(job_id)
    fetch_counts = FetchQueue(db).stats(job_id)
    total_candidates = sum(candidate_counts.values())
    return {
        "total_candidates": total_candidates,
        "new_candidates": candidate_counts.get("new", 0),
        "accepted_candidates": candidate_counts.get("accepted", 0),
        "duplicate_candidates": candidate_counts.get("duplicate", 0),
        "rejected_candidates": candidate_counts.get("rejected", 0),
        "review_candidates": candidate_counts.get("review", 0),
        "candidate_counts_by_status": candidate_counts,
        "fetch_done": fetch_counts.get("done", 0),
        "fetch_queued": fetch_counts.get("queued", 0),
        "fetch_failed": fetch_counts.get("failed", 0),
        "fetch_skipped": fetch_counts.get("skipped", 0),
        "fetch_counts_by_status": fetch_counts,
    }


# Mapping from the existing `ReviewReason` enum (models/enums.py, not
# duplicated here) to the coarser buckets this DB's review dashboard wants.
# Only reasons with an unambiguous correspondence are mapped; everything
# else reports as "unknown" rather than guessing -- Phase 1B can extend
# this mapping (or add a dedicated review sub-classifier) without any
# dashboard/template change, since callers only ever see bucket keys.
REVIEW_REASON_BUCKETS: dict[str, str] = {
    ReviewReason.CAPTCHA: "captcha",
    ReviewReason.BLOCKED: "http_error",
    ReviewReason.PARSE_FAILURE: "parse_failure",
    ReviewReason.DUPLICATE_AMBIGUITY: "genuine_duplicate",
    # A love_hotel candidate that reached extraction but had no name is,
    # in this specific job, most often an area/listing page that slipped
    # past the adapter's weak `is_facility_page` gate -- see
    # docs/lovehotel_couples_db.md "Facility-vs-listing classification".
    # Best-effort until Phase 1B adds a dedicated signal.
    ReviewReason.MISSING_REQUIRED_FIELD: "listing",
}
REVIEW_BUCKET_UNKNOWN = "unknown"

REVIEW_BUCKET_LABELS: dict[str, str] = {
    "http_error": "HTTP Error",
    "listing": "Listing",
    "captcha": "Captcha",
    "parse_failure": "Parse Failure",
    "genuine_duplicate": "Genuine Duplicate",
    REVIEW_BUCKET_UNKNOWN: "Unknown",
}
REVIEW_BUCKET_ORDER = ("http_error", "listing", "captcha", "parse_failure", "genuine_duplicate", REVIEW_BUCKET_UNKNOWN)


def review_breakdown(db: Database, job_id: str = LOVEHOTEL_JOB_ID) -> dict[str, Any]:
    """Open review-queue items for this job, grouped by reason (one SQL
    `GROUP BY`) and then bucketed in Python (a handful of distinct reason
    strings, not a per-row scan).
    """
    rows = db.query(
        "SELECT reason, COUNT(*) AS n FROM review_queue WHERE job_id=? AND status='open' GROUP BY reason",
        (job_id,),
    )
    buckets = {key: 0 for key in REVIEW_BUCKET_ORDER}
    for row in rows:
        bucket = REVIEW_REASON_BUCKETS.get(row["reason"], REVIEW_BUCKET_UNKNOWN)
        buckets[bucket] += row["n"]
    total_open = sum(buckets.values())
    return {
        "total_open": total_open,
        "buckets": buckets,
        "labels": REVIEW_BUCKET_LABELS,
        "order": REVIEW_BUCKET_ORDER,
    }


def job_status_summary(db: Database, job_id: str = LOVEHOTEL_JOB_ID) -> dict[str, Any] | None:
    """The job row plus its most recent run, read directly (no write, no
    job-registry mutation) -- mirrors what `/jobs/{job_id}` already shows,
    just narrowed to this one job for the dashboard card.
    """
    job = db.query_one("SELECT * FROM jobs WHERE job_id=?", (job_id,))
    if not job:
        return None
    job = dict(job)
    last_run = db.query_one(
        "SELECT * FROM run_history WHERE job_id=? ORDER BY started_at DESC, rowid DESC LIMIT 1",
        (job_id,),
    )
    return {
        "job_id": job["job_id"],
        "job_name": job["job_name"],
        "enabled": bool(job["enabled"]),
        "status": job["status"],
        "phase": job["phase"],
        "last_started_at": job["last_started_at"],
        "last_finished_at": job["last_finished_at"],
        "last_run": dict(last_run) if last_run else None,
    }


class CompletionGate:
    NATIONWIDE_COVERAGE = "nationwide_coverage"
    DATA_QUALITY = "data_quality"
    REVIEW_QUEUE = "review_queue"
    COLLECTION_QUEUE = "collection_queue"
    STORE_PICKER_OUTPUT = "store_picker_output"
    ATTRIBUTE_ENRICHMENT = "attribute_enrichment"

    ORDER = (
        NATIONWIDE_COVERAGE, DATA_QUALITY, REVIEW_QUEUE, COLLECTION_QUEUE,
        STORE_PICKER_OUTPUT, ATTRIBUTE_ENRICHMENT,
    )

    LABELS = {
        NATIONWIDE_COVERAGE: "全国カバレッジ",
        DATA_QUALITY: "データ品質",
        REVIEW_QUEUE: "Review整理",
        COLLECTION_QUEUE: "収集キュー",
        STORE_PICKER_OUTPUT: "Store Picker出力",
        ATTRIBUTE_ENRICHMENT: "属性補完",
    }


def completion_status(
    db: Database,
    job_id: str = LOVEHOTEL_JOB_ID,
    *,
    classification: dict[str, Any] | None = None,
    coverage: dict[str, Any] | None = None,
    review: dict[str, Any] | None = None,
    collection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Every gate is a real, live check -- there is no code path that
    reports the DB as complete short of every gate actually passing. Two
    gates (Store Picker output, attribute enrichment) have no data source
    anywhere in this codebase yet (no store-picker export exists, and
    Phase 1 deliberately never collects price/rooms/plans -- see
    `adapters/lovehotel_couples.py` module docstring), so they always
    report NOT MET rather than being guessed or omitted.

    Accepts already-computed sub-summaries (see `lovehotel_summary`) to
    avoid re-querying/re-classifying the same entities multiple times in
    one request; called standalone, it computes each of them itself.
    """
    classification = classification or classification_counts(db, job_id)
    coverage = coverage or coverage_summary(db, job_id, classification=classification)
    review = review if review is not None else review_breakdown(db, job_id)
    collection = collection or collection_summary(db, job_id)

    gates = {
        CompletionGate.NATIONWIDE_COVERAGE: coverage["prefecture_covered_count"] >= PREFECTURE_TOTAL,
        CompletionGate.DATA_QUALITY: (
            classification["total"] > 0
            and classification["counts"][LoveHotelCategory.LISTING] == 0
            and classification["counts"][LoveHotelCategory.HOMEPAGE] == 0
            and classification["counts"][LoveHotelCategory.UNKNOWN] == 0
            and classification["counts"][LoveHotelCategory.INCOMPLETE] == 0
        ),
        CompletionGate.REVIEW_QUEUE: review["total_open"] == 0,
        CompletionGate.COLLECTION_QUEUE: collection["fetch_queued"] == 0 and collection["new_candidates"] == 0,
        # No store-picker export pipeline exists in this codebase yet.
        CompletionGate.STORE_PICKER_OUTPUT: False,
        # Phase 1 is population formation only; price/rooms/plans are
        # explicitly out of scope (see the adapter's module docstring).
        CompletionGate.ATTRIBUTE_ENRICHMENT: False,
    }
    complete = all(gates.values())
    return {
        "gates": gates,
        "labels": CompletionGate.LABELS,
        "order": CompletionGate.ORDER,
        "complete": complete,
    }


def lovehotel_summary(db: Database, job_id: str = LOVEHOTEL_JOB_ID) -> dict[str, Any]:
    """Everything the Admin Dashboard's 全国ラブホテルDB section needs, in one
    call. `db_present` is False (and every count is zero) when this job
    hasn't been synced into the target database at all yet -- callers
    should treat that as "section not applicable", not as "0 facilities".
    """
    job = job_status_summary(db, job_id)
    classification = classification_counts(db, job_id)
    coverage = coverage_summary(db, job_id, classification=classification)
    collection = collection_summary(db, job_id)
    review = review_breakdown(db, job_id)
    completion = completion_status(
        db, job_id, classification=classification, coverage=coverage, review=review, collection=collection,
    )
    return {
        "job_id": job_id,
        "db_present": job is not None or classification["total"] > 0,
        "job": job,
        # `by_category` (the raw entity rows behind each bucket) is dropped
        # here -- it's only needed internally by coverage_summary above,
        # and would otherwise make this summary (and its CLI/JSON dump)
        # scale with the entity count instead of staying a fixed handful
        # of numbers.
        "classification": {"total": classification["total"], "counts": classification["counts"]},
        "coverage": coverage,
        "collection": collection,
        "review": review,
        "completion": completion,
    }
