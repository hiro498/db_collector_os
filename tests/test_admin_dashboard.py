from __future__ import annotations

from fastapi.testclient import TestClient

from db_collector_os.admin.app import create_app
from db_collector_os.config import AppConfig
from db_collector_os.database import Database
from db_collector_os.entities import EntityStore, EvidenceStore
from db_collector_os.job_registry import JobRegistry
from db_collector_os.lovehotel_audit import LOVEHOTEL_ADAPTER, LOVEHOTEL_JOB_ID
from db_collector_os.models.enums import JobPhase

from .conftest import insert_job


def _client(app_config: AppConfig) -> TestClient:
    return TestClient(create_app(app_config))


def _make_lovehotel_job(db: Database, **overrides) -> str:
    defaults = dict(
        job_name="Love Hotel Nationwide - Couples",
        category="love_hotel",
        target_db="lovehotel_facilities",
        target_table="entities",
        collector_type="local_business",
        adapter=LOVEHOTEL_ADAPTER,
        enabled=False,
        phase=JobPhase.COLLECT,
    )
    defaults.update(overrides)
    return insert_job(db, job_id=LOVEHOTEL_JOB_ID, **defaults)


def _add_facility(db: Database, name: str, url: str, prefecture: str, confidence: float = 0.75) -> None:
    entities = EntityStore(db)
    evidence = EvidenceStore(db)
    entity_id = entities.create(
        job_id=LOVEHOTEL_JOB_ID, entity_type="love_hotel", name=name, normalized_name=name,
        canonical_url=url, domain="couples.jp", address=f"{prefecture}1-1", telephone=None,
        external_id=None, fingerprint=f"fp-{name}",
        data={"prefecture": prefecture, "city": "X市"},
    )
    evidence.record_many(entity_id, {"name": name}, source_url=url, confidence=confidence)


class TestExistingFigureDashboardRegression:
    """The pre-existing dashboard must render exactly as before when the
    love hotel job doesn't exist -- this is the DB used by every other job
    (e.g. job_prod_figure_official_site) in normal operation."""

    def test_dashboard_renders_without_lovehotel_job(self, app_config: AppConfig, db: Database):
        insert_job(db, job_id="job_prod_figure", category="figure")
        client = _client(app_config)
        resp = client.get("/")
        assert resp.status_code == 200
        assert "Registered DBs" in resp.text
        assert "Review Queue" in resp.text
        assert "全国ラブホテルDB" not in resp.text

    def test_dbs_page_still_works(self, app_config: AppConfig, db: Database):
        insert_job(db, job_id="job_prod_figure", category="figure")
        client = _client(app_config)
        resp = client.get("/dbs")
        assert resp.status_code == 200

    def test_review_page_still_works(self, app_config: AppConfig, db: Database):
        client = _client(app_config)
        resp = client.get("/review")
        assert resp.status_code == 200

    def test_job_detail_page_still_works(self, app_config: AppConfig, db: Database):
        insert_job(db, job_id="job_prod_figure", category="figure")
        client = _client(app_config)
        resp = client.get("/jobs/job_prod_figure")
        assert resp.status_code == 200

    def test_dashboard_survives_an_incompatible_lovehotel_audit_module(
        self, app_config: AppConfig, db: Database, monkeypatch,
    ):
        """`lovehotel_audit` is expected to evolve independently (Phase 1B
        classification work) -- an API this dashboard doesn't recognize yet
        (missing key, changed shape) must degrade to "section omitted", not
        break every other Admin Dashboard route.
        """
        import db_collector_os.lovehotel_audit as lovehotel_audit

        _make_lovehotel_job(db)

        def incompatible_summary(db, job_id):
            return {"db_present": True, "totally_different_shape": True}

        monkeypatch.setattr(lovehotel_audit, "lovehotel_summary", incompatible_summary)
        client = _client(app_config)
        resp = client.get("/")
        assert resp.status_code == 200
        assert "全国ラブホテルDB" not in resp.text
        assert "Registered DBs" in resp.text


class TestLovehotelDashboardSection:
    def test_section_appears_when_job_exists(self, app_config: AppConfig, db: Database):
        _make_lovehotel_job(db)
        client = _client(app_config)
        resp = client.get("/")
        assert resp.status_code == 200
        assert "全国ラブホテルDB" in resp.text

    def test_valid_facility_count_is_not_raw_entity_total(self, app_config: AppConfig, db: Database):
        _make_lovehotel_job(db)
        _add_facility(db, "Hotel A", "https://couples.jp/hotel/1/", "東京都", confidence=0.75)
        for i in range(10):
            _add_facility(db, f"Listing {i}", f"https://couples.jp/area/13/?p={i}", "東京都", confidence=0.55)

        client = _client(app_config)
        ctx_resp = client.get("/")
        assert ctx_resp.status_code == 200
        # 11 total entities, but only 1 is a genuine facility -- the raw
        # total must never be shown as "有効施設".
        assert ">1<" in ctx_resp.text  # 有効施設 card value
        assert ">11<" in ctx_resp.text  # 総Entity card value

    def test_classification_and_coverage_values_match_summary(self, app_config: AppConfig, db: Database):
        _make_lovehotel_job(db)
        _add_facility(db, "Hotel A", "https://couples.jp/hotel/1/", "東京都", confidence=0.75)
        _add_facility(db, "Hotel B", "https://couples.jp/hotel/2/", "大阪府", confidence=0.75)

        from db_collector_os.lovehotel_audit import lovehotel_summary

        summary = lovehotel_summary(db, LOVEHOTEL_JOB_ID)
        assert summary["classification"]["counts"]["facility"] == 2
        assert summary["coverage"]["prefecture_covered_count"] == 2

        client = _client(app_config)
        resp = client.get("/")
        assert "2 / 47" in resp.text  # prefecture coverage card

    def test_job_status_paused_collect_shown(self, app_config: AppConfig, db: Database):
        _make_lovehotel_job(db)
        JobRegistry(db).pause(LOVEHOTEL_JOB_ID)
        client = _client(app_config)
        resp = client.get("/")
        assert "job_prod_lovehotel_couples" in resp.text
        assert "collect" in resp.text
        assert "paused" in resp.text

    def test_completion_always_reports_incomplete(self, app_config: AppConfig, db: Database):
        _make_lovehotel_job(db)
        for i, pref in enumerate([
            "北海道", "青森県", "岩手県", "宮城県", "秋田県",
        ]):
            _add_facility(db, f"Hotel {i}", f"https://couples.jp/hotel/{i}/", pref, confidence=0.75)

        client = _client(app_config)
        resp = client.get("/")
        assert "未完成" in resp.text
        assert "NATIONWIDE_LOVEHOTEL_DB_COMPLETE" in resp.text
        # Must never render as complete/100%.
        assert "NATIONWIDE_LOVEHOTEL_DB_COMPLETE=YES" not in resp.text
