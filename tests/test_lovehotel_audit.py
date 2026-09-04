from __future__ import annotations

from db_collector_os import lovehotel_audit
from db_collector_os.database import Database
from db_collector_os.entities import EntityStore, EvidenceStore
from db_collector_os.job_registry import JobRegistry, now_iso
from db_collector_os.lovehotel_audit import (
    LoveHotelCategory,
    classification_counts,
    classify_entity,
    collection_summary,
    completion_status,
    coverage_summary,
    job_status_summary,
    lovehotel_summary,
    review_breakdown,
)
from db_collector_os.models.enums import JobPhase, JobStatus, ReviewReason
from db_collector_os.review import ReviewQueue

from .conftest import insert_job

JOB_ID = lovehotel_audit.LOVEHOTEL_JOB_ID


def _make_job(db: Database, **overrides) -> str:
    defaults = dict(
        job_name="Love Hotel Nationwide - Couples",
        category="love_hotel",
        target_db="lovehotel_facilities",
        target_table="entities",
        collector_type="local_business",
        adapter=lovehotel_audit.LOVEHOTEL_ADAPTER,
    )
    defaults.update(overrides)
    return insert_job(db, job_id=JOB_ID, **defaults)


def _add_entity(
    db: Database,
    job_id: str,
    *,
    name: str,
    canonical_url: str | None,
    address: str | None = None,
    prefecture: str | None = None,
    city: str | None = None,
    operating_status: str | None = None,
    confidence: float | None,
) -> str:
    entities = EntityStore(db)
    evidence = EvidenceStore(db)
    entity_id = entities.create(
        job_id=job_id,
        entity_type=lovehotel_audit.LOVEHOTEL_ENTITY_TYPE,
        name=name,
        normalized_name=name,
        canonical_url=canonical_url,
        domain="couples.jp",
        address=address,
        telephone=None,
        external_id=None,
        fingerprint=f"fp-{name}",
        data={
            "prefecture": prefecture,
            "city": city,
            "operating_status": operating_status,
            "source_name": "Couples",
        },
    )
    if confidence is not None:
        evidence.record_many(
            entity_id,
            {"name": name, "prefecture": prefecture, "city": city},
            source_url=canonical_url or "https://couples.jp/",
            confidence=confidence,
        )
    return entity_id


class TestClassifyEntity:
    def test_strong_confidence_with_location_is_facility(self):
        entity = {
            "canonical_url": "https://couples.jp/hotel/12345/",
            "address": "東京都新宿区1-2-3",
            "data": {"prefecture": "東京都", "city": "新宿区"},
        }
        assert classify_entity(entity, 0.75) == LoveHotelCategory.FACILITY

    def test_weak_confidence_with_location_is_listing(self):
        entity = {
            "canonical_url": "https://couples.jp/area/13/",
            "address": "東京都渋谷区9-9-9",
            "data": {"prefecture": "東京都", "city": "渋谷区"},
        }
        assert classify_entity(entity, 0.55) == LoveHotelCategory.LISTING

    def test_homepage_root_path(self):
        entity = {"canonical_url": "https://couples.jp/", "address": None, "data": {}}
        assert classify_entity(entity, 0.55) == LoveHotelCategory.HOMEPAGE

    def test_homepage_empty_path(self):
        entity = {"canonical_url": "https://couples.jp", "address": None, "data": {}}
        assert classify_entity(entity, 0.75) == LoveHotelCategory.HOMEPAGE

    def test_closed_marker_wins_over_everything_else(self):
        entity = {
            "canonical_url": "https://couples.jp/hotel/999/",
            "address": "大阪府大阪市1-1-1",
            "data": {"prefecture": "大阪府", "city": "大阪市", "operating_status": "closed"},
        }
        assert classify_entity(entity, 0.75) == LoveHotelCategory.CLOSED

    def test_no_location_at_all_is_incomplete(self):
        entity = {"canonical_url": "https://couples.jp/hotel/1/", "address": None, "data": {}}
        assert classify_entity(entity, 0.55) == LoveHotelCategory.INCOMPLETE

    def test_no_evidence_at_all_is_unknown(self):
        entity = {
            "canonical_url": "https://couples.jp/hotel/1/",
            "address": "東京都千代田区1-1",
            "data": {"prefecture": "東京都"},
        }
        assert classify_entity(entity, None) == LoveHotelCategory.UNKNOWN


class TestClassificationCounts:
    def test_partitions_sum_to_total_and_separates_facility_from_listing(self, db: Database):
        _make_job(db)
        _add_entity(
            db, JOB_ID, name="Hotel A", canonical_url="https://couples.jp/hotel/1001/",
            address="東京都新宿区1-1", prefecture="東京都", city="新宿区", confidence=0.75,
        )
        _add_entity(
            db, JOB_ID, name="Hotel B", canonical_url="https://couples.jp/hotel/1002/",
            address="大阪府大阪市2-2", prefecture="大阪府", city="大阪市", confidence=0.75,
        )
        for i in range(5):
            _add_entity(
                db, JOB_ID, name=f"Area Listing {i}", canonical_url=f"https://couples.jp/area/13/?page={i}",
                address="東京都渋谷区9-9", prefecture="東京都", city="渋谷区", confidence=0.55,
            )
        _add_entity(db, JOB_ID, name="Top Page", canonical_url="https://couples.jp/", confidence=0.55)
        _add_entity(
            db, JOB_ID, name="Hotel C (closed)", canonical_url="https://couples.jp/hotel/1003/",
            address="東京都渋谷区5-5", prefecture="東京都", city="渋谷区",
            operating_status="closed", confidence=0.75,
        )
        _add_entity(db, JOB_ID, name="Hotel D (no location)", canonical_url="https://couples.jp/hotel/1004/", confidence=0.55)
        _add_entity(db, JOB_ID, name="Hotel E (no evidence)", canonical_url="https://couples.jp/hotel/1005/", confidence=None)

        result = classification_counts(db, JOB_ID)
        counts = result["counts"]

        assert result["total"] == 11
        assert sum(counts.values()) == result["total"]
        assert counts[LoveHotelCategory.FACILITY] == 2
        assert counts[LoveHotelCategory.LISTING] == 5
        assert counts[LoveHotelCategory.HOMEPAGE] == 1
        assert counts[LoveHotelCategory.CLOSED] == 1
        assert counts[LoveHotelCategory.INCOMPLETE] == 1
        assert counts[LoveHotelCategory.UNKNOWN] == 1
        # The core requirement: raw entity total must never be presented as
        # the valid facility count.
        assert counts[LoveHotelCategory.FACILITY] != result["total"]

    def test_empty_job_reports_zero_everything(self, db: Database):
        _make_job(db)
        result = classification_counts(db, JOB_ID)
        assert result["total"] == 0
        assert all(n == 0 for n in result["counts"].values())


class TestCoverageSummary:
    def test_coverage_excludes_listing_and_homepage(self, db: Database):
        _make_job(db)
        _add_entity(
            db, JOB_ID, name="Hotel A", canonical_url="https://couples.jp/hotel/1/",
            address="東京都新宿区1-1", prefecture="東京都", city="新宿区", confidence=0.75,
        )
        _add_entity(
            db, JOB_ID, name="Hotel B (closed)", canonical_url="https://couples.jp/hotel/2/",
            address="大阪府大阪市2-2", prefecture="大阪府", city=None,
            operating_status="closed", confidence=0.75,
        )
        # A mass of mis-accepted listing pages spanning many prefectures --
        # must NOT count toward prefecture coverage.
        for pref in ("北海道", "沖縄県", "福岡県"):
            _add_entity(
                db, JOB_ID, name=f"Listing {pref}", canonical_url="https://couples.jp/area/9999/",
                address=f"{pref}1-1", prefecture=pref, city="X市", confidence=0.55,
            )

        coverage = coverage_summary(db, JOB_ID)
        assert coverage["real_facility_total"] == 2
        assert coverage["prefecture_covered_count"] == 2
        assert coverage["covered_prefectures"] == ["大阪府", "東京都"]
        assert coverage["prefecture_total"] == 47
        assert coverage["prefecture_coverage_ratio"] == 2 / 47
        assert coverage["prefecture_info_rate"] == 1.0  # both real rows have a prefecture
        assert coverage["city_info_rate"] == 0.5  # only Hotel A has a city


class TestCollectionSummary:
    def test_candidate_and_fetch_queue_counts_via_group_by(self, db: Database):
        _make_job(db)
        db.execute(
            "INSERT INTO entity_candidates (candidate_id, job_id, entity_type, status, discovered_at) "
            "VALUES (?,?,?,?,?)",
            ("c1", JOB_ID, "love_hotel", "new", now_iso()),
        )
        db.execute(
            "INSERT INTO entity_candidates (candidate_id, job_id, entity_type, status, discovered_at) "
            "VALUES (?,?,?,?,?)",
            ("c2", JOB_ID, "love_hotel", "accepted", now_iso()),
        )
        db.execute(
            "INSERT INTO entity_candidates (candidate_id, job_id, entity_type, status, discovered_at) "
            "VALUES (?,?,?,?,?)",
            ("c3", JOB_ID, "love_hotel", "duplicate", now_iso()),
        )
        db.execute(
            "INSERT INTO fetch_queue (job_id, url, domain, status, created_at) VALUES (?,?,?,?,?)",
            (JOB_ID, "https://couples.jp/a", "couples.jp", "done", now_iso()),
        )
        db.execute(
            "INSERT INTO fetch_queue (job_id, url, domain, status, created_at) VALUES (?,?,?,?,?)",
            (JOB_ID, "https://couples.jp/b", "couples.jp", "queued", now_iso()),
        )

        summary = collection_summary(db, JOB_ID)
        assert summary["total_candidates"] == 3
        assert summary["new_candidates"] == 1
        assert summary["accepted_candidates"] == 1
        assert summary["duplicate_candidates"] == 1
        assert summary["fetch_done"] == 1
        assert summary["fetch_queued"] == 1
        assert summary["fetch_failed"] == 0


class TestReviewBreakdown:
    def test_reasons_map_to_expected_buckets(self, db: Database):
        _make_job(db)
        review = ReviewQueue(db)
        review.add(JOB_ID, ReviewReason.CAPTCHA)
        review.add(JOB_ID, ReviewReason.BLOCKED)
        review.add(JOB_ID, ReviewReason.PARSE_FAILURE)
        review.add(JOB_ID, ReviewReason.DUPLICATE_AMBIGUITY)
        review.add(JOB_ID, ReviewReason.MISSING_REQUIRED_FIELD)
        review.add(JOB_ID, ReviewReason.LOW_CONFIDENCE)  # unmapped -> unknown

        result = review_breakdown(db, JOB_ID)
        assert result["total_open"] == 6
        assert result["buckets"]["captcha"] == 1
        assert result["buckets"]["http_error"] == 1
        assert result["buckets"]["parse_failure"] == 1
        assert result["buckets"]["genuine_duplicate"] == 1
        assert result["buckets"]["listing"] == 1
        assert result["buckets"]["unknown"] == 1

    def test_resolved_reviews_are_not_counted(self, db: Database):
        _make_job(db)
        review = ReviewQueue(db)
        review_id = review.add(JOB_ID, ReviewReason.CAPTCHA)
        review.resolve(review_id)
        result = review_breakdown(db, JOB_ID)
        assert result["total_open"] == 0


class TestJobStatusSummary:
    def test_reports_paused_collect_job(self, db: Database):
        _make_job(db, enabled=0, phase=JobPhase.COLLECT)
        JobRegistry(db).pause(JOB_ID)
        status = job_status_summary(db, JOB_ID)
        assert status is not None
        assert status["enabled"] is False
        assert status["status"] == JobStatus.PAUSED
        assert status["phase"] == JobPhase.COLLECT

    def test_missing_job_returns_none(self, db: Database):
        assert job_status_summary(db, JOB_ID) is None


class TestCompletionStatus:
    def test_never_reports_complete_without_a_store_picker_pipeline(self, db: Database):
        _make_job(db)
        # Build a suspiciously "perfect-looking" facility set: all 47
        # prefectures covered, no listing/homepage/incomplete/unknown rows,
        # nothing left in review or the fetch queue.
        for i, pref in enumerate(lovehotel_audit.PREFECTURES):
            _add_entity(
                db, JOB_ID, name=f"Hotel {i}", canonical_url=f"https://couples.jp/hotel/{2000 + i}/",
                address=f"{pref}1-1", prefecture=pref, city="X市", confidence=0.75,
            )

        result = completion_status(db, JOB_ID)
        assert result["gates"][lovehotel_audit.CompletionGate.NATIONWIDE_COVERAGE] is True
        assert result["gates"][lovehotel_audit.CompletionGate.DATA_QUALITY] is True
        # Store-picker output / attribute enrichment have no implementation
        # anywhere in this codebase -- completion must stay NO regardless.
        assert result["gates"][lovehotel_audit.CompletionGate.STORE_PICKER_OUTPUT] is False
        assert result["gates"][lovehotel_audit.CompletionGate.ATTRIBUTE_ENRICHMENT] is False
        assert result["complete"] is False

    def test_incomplete_real_db_state_is_not_complete(self, db: Database):
        _make_job(db)
        _add_entity(
            db, JOB_ID, name="Hotel A", canonical_url="https://couples.jp/hotel/1/",
            address="東京都新宿区1-1", prefecture="東京都", city="新宿区", confidence=0.75,
        )
        result = completion_status(db, JOB_ID)
        assert result["complete"] is False


class TestLovehotelSummary:
    def test_reports_db_not_present_when_job_missing(self, db: Database):
        summary = lovehotel_summary(db, JOB_ID)
        assert summary["db_present"] is False
        assert summary["classification"]["total"] == 0

    def test_full_summary_shape(self, db: Database):
        _make_job(db)
        _add_entity(
            db, JOB_ID, name="Hotel A", canonical_url="https://couples.jp/hotel/1/",
            address="東京都新宿区1-1", prefecture="東京都", city="新宿区", confidence=0.75,
        )
        summary = lovehotel_summary(db, JOB_ID)
        assert summary["db_present"] is True
        assert summary["job"]["job_id"] == JOB_ID
        assert summary["classification"]["counts"][LoveHotelCategory.FACILITY] == 1
        assert summary["coverage"]["prefecture_covered_count"] == 1
        assert summary["completion"]["complete"] is False
