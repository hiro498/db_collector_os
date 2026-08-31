"""Validates config/jobs/prod_lovehotel_couples.yaml through the real
`db-collector jobs sync` CLI path (not a re-implementation of the loader),
and checks it never collides with, or is confused for, any pre-existing
job (sample jobs or the first production DB's job).
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from click.testing import CliRunner

from db_collector_os.cli import main

REPO_ROOT = Path(__file__).parent.parent
PROD_JOB_YAML = REPO_ROOT / "config" / "jobs" / "prod_lovehotel_couples.yaml"


def test_production_job_yaml_exists_and_is_well_formed():
    assert PROD_JOB_YAML.exists()
    spec = yaml.safe_load(PROD_JOB_YAML.read_text(encoding="utf-8"))
    assert spec["job_id"] == "job_prod_lovehotel_couples"
    assert spec["category"] == "love_hotel"
    assert spec["target_db"] == "lovehotel_facilities"
    assert spec["collector_type"] == "local_business"
    assert spec["adapter"] == "lovehotel_couples"
    assert spec["enabled"] is False  # must not auto-run until the VPS preflight passes
    assert spec["config"]["seed_urls"] == ["https://couples.jp/"]
    assert spec["max_pages"] <= 50  # conservative first Phase-1 run
    assert spec["rate_limit"] >= 2.0  # conservative per-domain pacing
    assert spec["concurrency"] == 1

    discovery = spec["config"]["discovery"]
    # never auto-follows sameAs / arbitrary related-entity links -- see the
    # YAML's own comments for why (official-site containment).
    assert discovery["related_entities"] is False
    assert set(discovery["allowed_domains"]) <= {"couples.jp", "www.couples.jp"}
    # Happy Hotel / NAVITIME must never appear anywhere in this job's config.
    dumped = yaml.safe_dump(spec)
    assert "happyhotel" not in dumped.lower()
    assert "navitime" not in dumped.lower()


def test_product_url_pattern_excludes_login_inquiries_api_but_allows_navigation_and_detail_pages():
    """A long-running production test found the job's fetch_queue filled
    with couples.jp URLs that can never yield a facility (login page,
    inquiry form, the site's own internal JSON API -- see the YAML's own
    comments for the confirmed real examples). This is a confirmed-junk
    EXCLUSION pattern, not a guess at the real facility-detail URL shape --
    it must still pass prefecture/city/area/reservation search-results
    listing pages (`/hotels/search-by/...`), which remain essential
    navigation for reaching real facility links (see
    lovehotel_couples.py::_is_excluded_url for the adapter-side veto that
    keeps those from ever being entity-ized instead).
    """
    spec = yaml.safe_load(PROD_JOB_YAML.read_text(encoding="utf-8"))
    pattern = spec["config"]["discovery"]["product_url_pattern"]
    compiled = re.compile(pattern)

    assert not compiled.search("https://couples.jp/login")
    assert not compiled.search("https://couples.jp/login/")
    assert not compiled.search("https://couples.jp/inquiries/input")
    assert not compiled.search("https://couples.jp/api/prefectures/selectable")

    assert compiled.search("https://couples.jp/hotels/search-by/prefectures/7/reservation_all")
    assert compiled.search("https://couples.jp/hotels/search-by/cities/567/reservation_all")
    assert compiled.search("https://couples.jp/hotel/12345/")
    assert compiled.search("https://couples.jp/privacy")

    # enabled must stay false regardless of this discovery-config change:
    assert spec["enabled"] is False


def test_job_id_does_not_collide_with_other_jobs():
    other_ids = set()
    other_target_dbs = set()
    jobs_dir = REPO_ROOT / "config" / "jobs"
    for path in jobs_dir.glob("*.yaml"):
        if path == PROD_JOB_YAML:
            continue
        other_spec = yaml.safe_load(path.read_text(encoding="utf-8"))
        other_ids.add(other_spec["job_id"])
        other_target_dbs.add(other_spec.get("target_db"))

    prod_spec = yaml.safe_load(PROD_JOB_YAML.read_text(encoding="utf-8"))
    assert prod_spec["job_id"] not in other_ids
    assert prod_spec["target_db"] not in other_target_dbs


def _sync_real_config(tmp_path, monkeypatch):
    """Runs the real `db-collector jobs sync` CLI command against the
    repo's actual config/default.yaml (and therefore its real
    config/jobs/*.yaml, every other job included), pointed at a throwaway
    DB so this never touches any real deployment data.
    """
    monkeypatch.delenv("DB_COLLECTOR_HOME", raising=False)
    monkeypatch.delenv("DB_COLLECTOR_DB_PATH", raising=False)
    home = tmp_path / "var"
    config_path = REPO_ROOT / "config" / "default.yaml"
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["--config", str(config_path), "migrate"],
        env={"DB_COLLECTOR_HOME": str(home), "DB_COLLECTOR_DB_PATH": "sync_test.sqlite3"},
    )
    assert result.exit_code == 0, result.output
    result = runner.invoke(
        main,
        ["--config", str(config_path), "jobs", "sync"],
        env={"DB_COLLECTOR_HOME": str(home), "DB_COLLECTOR_DB_PATH": "sync_test.sqlite3"},
    )
    assert result.exit_code == 0, result.output
    return home / "sync_test.sqlite3", result.output


def test_jobs_sync_registers_the_production_job_disabled(tmp_path, monkeypatch):
    db_path, output = _sync_real_config(tmp_path, monkeypatch)
    assert "job_prod_lovehotel_couples" in output

    from db_collector_os.database import Database
    from db_collector_os.job_registry import JobRegistry

    db = Database(db_path)
    jr = JobRegistry(db)
    job = jr.get("job_prod_lovehotel_couples")
    assert job is not None
    assert job["enabled"] is False
    assert job["adapter"] == "lovehotel_couples"
    assert job["collector_type"] == "local_business"
    assert job["config_json"]["discovery"]["related_entities"] is False

    # enabled=false -> never picked up by the scheduler on its own.
    due_ids = {j["job_id"] for j in jr.due_jobs()}
    assert "job_prod_lovehotel_couples" not in due_ids

    # Every pre-existing job (sample jobs and the first production DB) is
    # untouched/still present alongside it -- this sync never displaces or
    # deletes anything.
    assert jr.get("job_sample_local_business") is not None
    assert jr.get("job_sample_local_business")["enabled"] is False
    assert jr.get("job_prod_figure_official_site") is not None
    assert jr.get("job_prod_figure_official_site")["enabled"] is False
    db.close()
