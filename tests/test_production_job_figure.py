"""Validates the FIRST_PRODUCTION_DB job definition
(config/jobs/prod_figure_official_site.yaml) through the real `db-collector
jobs sync` CLI path -- not a re-implementation of the loader -- and checks it
never collides with, or is confused for, the pre-existing sample jobs.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from click.testing import CliRunner

from db_collector_os.cli import main

REPO_ROOT = Path(__file__).parent.parent
PROD_JOB_YAML = REPO_ROOT / "config" / "jobs" / "prod_figure_official_site.yaml"


def test_production_job_yaml_exists_and_is_well_formed():
    assert PROD_JOB_YAML.exists()
    spec = yaml.safe_load(PROD_JOB_YAML.read_text(encoding="utf-8"))
    assert spec["job_id"] == "job_prod_figure_official_site"
    assert spec["collector_type"] == "official_site"
    assert spec["adapter"] == "figure_official_site"
    assert spec["enabled"] is False  # must not auto-run until a real site is configured
    assert spec["config"]["seed_urls"]
    assert spec["max_pages"] <= 50  # conservative first Phase-1 run
    assert spec["rate_limit"] >= 2.0  # conservative per-domain pacing
    assert spec["concurrency"] == 1


def test_job_id_does_not_collide_with_sample_jobs():
    sample_ids = set()
    for path in (REPO_ROOT / "config" / "jobs").glob("sample_*.yaml"):
        sample_ids.add(yaml.safe_load(path.read_text(encoding="utf-8"))["job_id"])
    prod_spec = yaml.safe_load(PROD_JOB_YAML.read_text(encoding="utf-8"))
    assert prod_spec["job_id"] not in sample_ids
    assert prod_spec["target_db"] not in {"sample_products", "sample_local_businesses", "sample_people", "sample_api_products"}


def _sync_real_config(tmp_path, monkeypatch):
    """Runs the real `db-collector jobs sync` CLI command against the repo's
    actual config/default.yaml (and therefore its real config/jobs/*.yaml,
    sample jobs included), but pointed at a throwaway DB so this never
    touches any real deployment data.
    """
    monkeypatch.delenv("DB_COLLECTOR_HOME", raising=False)
    monkeypatch.delenv("DB_COLLECTOR_DB_PATH", raising=False)
    home = tmp_path / "var"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump({"home_dir": str(home), "db_path": "sync_test.sqlite3"}), encoding="utf-8"
    )
    # Point at the real jobs directory by re-using the repo's config/jobs/ layout:
    # AppConfig derives jobs_dir from config_path.parent/"jobs", so symlink-free
    # approach: copy the config_path next to the real config dir instead.
    real_config_dir = REPO_ROOT / "config"
    config_path = real_config_dir / "default.yaml"
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
    assert "job_prod_figure_official_site" in output

    from db_collector_os.database import Database
    from db_collector_os.job_registry import JobRegistry

    db = Database(db_path)
    jr = JobRegistry(db)
    job = jr.get("job_prod_figure_official_site")
    assert job is not None
    assert job["enabled"] is False
    assert job["adapter"] == "figure_official_site"
    assert job["collector_type"] == "official_site"

    # enabled=false -> never picked up by the scheduler on its own.
    due_ids = {j["job_id"] for j in jr.due_jobs()}
    assert "job_prod_figure_official_site" not in due_ids

    # Existing sample jobs are untouched/still present alongside it.
    assert jr.get("job_sample_official_site") is not None
    assert jr.get("job_sample_official_site")["enabled"] is False
    db.close()
