from __future__ import annotations

import json
from pathlib import Path

import responses
import yaml
from click.testing import CliRunner

from db_collector_os.cli import main

_HTML = """<!doctype html><html><head><title>渋谷ラーメンおすすめランキング</title>
<link rel="canonical" href="https://example.jp/ramen/"></head><body>
<main><h1>渋谷ラーメンおすすめランキング</h1><p>渋谷のラーメン店を紹介します。</p></main>
</body></html>"""


def _write_config(tmp_path: Path, monkeypatch) -> Path:
    home = tmp_path / "var"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump({"home_dir": str(home), "db_path": "ci_cli_test.sqlite3"}), encoding="utf-8")
    monkeypatch.delenv("DB_COLLECTOR_HOME", raising=False)
    monkeypatch.delenv("DB_COLLECTOR_DB_PATH", raising=False)
    return config_path


def test_ci_group_is_registered_without_touching_existing_commands(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path, monkeypatch)
    runner = CliRunner()
    result = runner.invoke(main, ["--config", str(config_path), "--help"])
    assert result.exit_code == 0
    assert "ci" in result.output
    assert "jobs" in result.output  # existing commands still present


@responses.activate
def test_ci_analyze_lp_and_status(tmp_path, monkeypatch):
    responses.add(responses.GET, "https://example.jp/ramen/", body=_HTML, content_type="text/html")
    config_path = _write_config(tmp_path, monkeypatch)
    runner = CliRunner()

    result = runner.invoke(main, ["--config", str(config_path), "ci", "analyze-lp", "https://example.jp/ramen/"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    run_id = data["run"]["crawl_run_id"]
    assert data["run"]["status"] == "completed"

    result = runner.invoke(main, ["--config", str(config_path), "ci", "status", run_id])
    assert result.exit_code == 0
    assert json.loads(result.output)["run"]["crawl_run_id"] == run_id


@responses.activate
def test_ci_export_writes_csv_files(tmp_path, monkeypatch):
    responses.add(responses.GET, "https://example.jp/ramen/", body=_HTML, content_type="text/html")
    config_path = _write_config(tmp_path, monkeypatch)
    runner = CliRunner()
    result = runner.invoke(main, ["--config", str(config_path), "ci", "analyze-lp", "https://example.jp/ramen/"])
    run_id = json.loads(result.output)["run"]["crawl_run_id"]

    out_dir = tmp_path / "exports"
    result = runner.invoke(
        main, ["--config", str(config_path), "ci", "export", run_id, "--out-dir", str(out_dir)]
    )
    assert result.exit_code == 0
    written = {Path(p).name for p in result.output.splitlines()}
    assert written == {"domain_summary.csv", "pages.csv", "keywords.csv", "page_keywords.csv", "crawl_audit.csv"}
    for name in written:
        assert (out_dir / name).exists()


def test_ci_status_reports_error_for_unknown_run(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path, monkeypatch)
    runner = CliRunner()
    result = runner.invoke(main, ["--config", str(config_path), "ci", "status", "no-such-run"])
    assert result.exit_code == 1
