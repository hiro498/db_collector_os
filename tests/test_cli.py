from __future__ import annotations

import json

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
