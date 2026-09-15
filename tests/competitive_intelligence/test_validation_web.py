from __future__ import annotations

import responses
from fastapi.testclient import TestClient

from db_collector_os.competitive_intelligence import service
from db_collector_os.competitive_intelligence.web.app import create_ci_app

from .fixtures.affiliate_site import BASE, build_fixture_site


def _register_fixture(rsps) -> None:
    pages = build_fixture_site()
    rsps.add(responses.GET, f"{BASE}/robots.txt", status=404)
    rsps.add(responses.GET, f"{BASE}/sitemap.xml", status=404)
    for url, html in pages.items():
        rsps.add(responses.GET, url, body=html, content_type="text/html")


def _run_fixture_validation(app_config) -> str:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        _register_fixture(rsps)
        return service.validate_domain(app_config, f"{BASE}/", max_pages=30, rate_limit=100_000.0)


def test_validations_list_empty(app_config):
    app = create_ci_app(app_config)
    client = TestClient(app)
    r = client.get("/validations")
    assert r.status_code == 200
    assert "Production Validations" in r.text


def test_validations_list_shows_completed_run(app_config):
    validation_run_id = _run_fixture_validation(app_config)
    app = create_ci_app(app_config)
    client = TestClient(app)
    r = client.get("/validations")
    assert r.status_code == 200
    assert BASE in r.text


def test_validation_detail_shows_target_keywords_and_kpi(app_config):
    validation_run_id = _run_fixture_validation(app_config)
    app = create_ci_app(app_config)
    client = TestClient(app)
    r = client.get(f"/validations/{validation_run_id}")
    assert r.status_code == 200
    assert "Target Keywords" in r.text
    assert "Not Observed" in r.text  # organic_rank/opportunity are unobserved in this fixture


def test_validation_detail_unknown_run_is_404(app_config):
    app = create_ci_app(app_config)
    client = TestClient(app)
    r = client.get("/validations/no-such-run")
    assert r.status_code == 404


def test_validation_export_route(app_config):
    validation_run_id = _run_fixture_validation(app_config)
    app = create_ci_app(app_config)
    client = TestClient(app)
    r = client.get(f"/validations/{validation_run_id}/export?file=target_keywords.csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")


def test_validation_export_rejects_unknown_file(app_config):
    validation_run_id = _run_fixture_validation(app_config)
    app = create_ci_app(app_config)
    client = TestClient(app)
    r = client.get(f"/validations/{validation_run_id}/export?file=../../etc/passwd", follow_redirects=False)
    assert r.status_code == 307


def test_validation_human_audit_route(app_config):
    validation_run_id = _run_fixture_validation(app_config)
    keywords = service.get_domain_keyword_summary(app_config, validation_run_id)
    sample = next(k for k in keywords if not k["is_noise"])

    app = create_ci_app(app_config)
    client = TestClient(app)
    r = client.post(f"/validations/{validation_run_id}/audit", data={
        "normalized_keyword": sample["normalized_keyword"], "audit_class": "B", "audit_note": "web audit",
    }, follow_redirects=False)
    assert r.status_code == 303

    updated = service.get_domain_keyword_summary(app_config, validation_run_id)
    updated_row = next(k for k in updated if k["normalized_keyword"] == sample["normalized_keyword"])
    assert updated_row["audit_class"] == "B"
    assert updated_row["audit_note"] == "web audit"
