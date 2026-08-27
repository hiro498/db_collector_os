from __future__ import annotations

import json

import responses
import yaml
from click.testing import CliRunner

from db_collector_os.cli import main


def _write_config(tmp_path, monkeypatch):
    home = tmp_path / "var"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump({"home_dir": str(home), "db_path": "cli_test.sqlite3"}), encoding="utf-8")
    monkeypatch.delenv("DB_COLLECTOR_HOME", raising=False)
    monkeypatch.delenv("DB_COLLECTOR_DB_PATH", raising=False)
    return config_path


def test_migrate_command(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path, monkeypatch)
    runner = CliRunner()
    result = runner.invoke(main, ["--config", str(config_path), "migrate"])
    assert result.exit_code == 0
    assert "integrity_check=ok" in result.output


def test_integrity_command(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path, monkeypatch)
    runner = CliRunner()
    result = runner.invoke(main, ["--config", str(config_path), "integrity"])
    assert result.exit_code == 0
    assert "ok" in result.output


def test_status_command_outputs_json(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path, monkeypatch)
    runner = CliRunner()
    result = runner.invoke(main, ["--config", str(config_path), "status"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["jobs_total"] == 0


def test_jobs_list_empty(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path, monkeypatch)
    runner = CliRunner()
    result = runner.invoke(main, ["--config", str(config_path), "jobs", "list"])
    assert result.exit_code == 0


def test_health_command(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path, monkeypatch)
    runner = CliRunner()
    result = runner.invoke(main, ["--config", str(config_path), "health"])
    data = json.loads(result.output)
    assert data["db_integrity_ok"] is True


def test_jobs_enable_disable_commands(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path, monkeypatch)
    runner = CliRunner()
    runner.invoke(main, ["--config", str(config_path), "migrate"])

    from db_collector_os.config import load_config
    from db_collector_os.database import Database
    from db_collector_os.job_registry import JobRegistry

    cfg = load_config(str(config_path))
    db = Database(cfg.db_path)
    job_id = JobRegistry(db).create(
        job_name="t", category="c", target_db="d", target_table="entities",
        collector_type="official_site", adapter="sample_official_site", enabled=False,
    )
    db.close()

    result = runner.invoke(main, ["--config", str(config_path), "jobs", "enable", job_id])
    assert result.exit_code == 0, result.output
    assert f"enabled {job_id}" in result.output

    db = Database(cfg.db_path)
    assert JobRegistry(db).get(job_id)["enabled"] is True
    db.close()

    result = runner.invoke(main, ["--config", str(config_path), "jobs", "disable", job_id])
    assert result.exit_code == 0, result.output
    db = Database(cfg.db_path)
    assert JobRegistry(db).get(job_id)["enabled"] is False
    db.close()


def test_jobs_enable_unknown_job_fails(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path, monkeypatch)
    runner = CliRunner()
    runner.invoke(main, ["--config", str(config_path), "migrate"])
    result = runner.invoke(main, ["--config", str(config_path), "jobs", "enable", "does_not_exist"])
    assert result.exit_code == 1


@responses.activate
def test_jobs_run_finishes_run_history_on_success(tmp_path, monkeypatch):
    """Regression test for the first production proof's run_history bug:
    `db-collector jobs run` used to call the collector directly and never
    finish the run_history row, leaving it stuck at status='running' with
    fetched_count=0/inserted_count=0/duration_seconds=None even though the
    job itself completed successfully.
    """
    responses.add(responses.GET, "https://example.com/robots.txt", status=404)
    responses.add(
        responses.GET, "https://example.com/p", status=200, content_type="text/html",
        body='<html><head><title>P</title><script type="application/ld+json">'
             '{"@type":"Product","name":"Widget"}</script></head><body><h1>Widget</h1></body></html>',
    )

    config_path = _write_config(tmp_path, monkeypatch)
    runner = CliRunner()
    runner.invoke(main, ["--config", str(config_path), "migrate"])

    from db_collector_os.config import load_config
    from db_collector_os.database import Database
    from db_collector_os.job_registry import JobRegistry

    cfg = load_config(str(config_path))
    db = Database(cfg.db_path)
    job_id = JobRegistry(db).create(
        job_name="t", category="product", target_db="d", target_table="entities",
        collector_type="official_site", adapter="sample_official_site",
        config={"seed_urls": ["https://example.com/p"]}, max_pages=5,
    )
    db.close()

    result = runner.invoke(main, ["--config", str(config_path), "jobs", "run", job_id])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] in ("completed", "retry")
    assert payload["fetched_count"] == 1
    assert payload["inserted_count"] == 1
    assert payload["error_count"] == 0

    db = Database(cfg.db_path)
    runs = db.query("SELECT * FROM run_history WHERE job_id=?", (job_id,))
    assert len(runs) == 1
    run = runs[0]
    assert run["status"] == "completed"
    assert run["finished_at"] is not None
    assert run["duration_seconds"] is not None
    assert run["fetched_count"] == 1
    assert run["inserted_count"] == 1
    assert run["error_count"] == 0
    db.close()


def test_jobs_run_finishes_run_history_on_failure(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path, monkeypatch)
    runner = CliRunner()
    runner.invoke(main, ["--config", str(config_path), "migrate"])

    from db_collector_os.config import load_config
    from db_collector_os.database import Database
    from db_collector_os.job_registry import JobRegistry

    cfg = load_config(str(config_path))
    db = Database(cfg.db_path)
    job_id = JobRegistry(db).create(
        job_name="t", category="product", target_db="d", target_table="entities",
        collector_type="official_site", adapter="does_not_exist_adapter",
        config={"seed_urls": ["https://example.com/p"]},
    )
    db.close()

    result = runner.invoke(main, ["--config", str(config_path), "jobs", "run", job_id])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["status"] == "failed"

    db = Database(cfg.db_path)
    runs = db.query("SELECT * FROM run_history WHERE job_id=?", (job_id,))
    assert len(runs) == 1
    assert runs[0]["status"] == "failed"
    assert runs[0]["finished_at"] is not None
    assert runs[0]["error_count"] == 1
    job = JobRegistry(db).get(job_id)
    assert job["status"] == "failed"
    db.close()
