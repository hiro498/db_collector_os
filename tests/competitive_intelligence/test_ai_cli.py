from __future__ import annotations

import json
from pathlib import Path

import responses
import yaml
from click.testing import CliRunner

from db_collector_os.cli import main

_HTML = """<!doctype html><html><head><title>渋谷ラーメンおすすめランキング</title>
<link rel="canonical" href="https://example.jp/ramen/"></head><body>
<main><h1>渋谷ラーメンおすすめランキング</h1><p>編集部が実際に調査した結果、同ジャンル100件中上位5%です。</p></main>
</body></html>"""


def _write_config(tmp_path: Path, monkeypatch) -> Path:
    home = tmp_path / "var"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump({"home_dir": str(home), "db_path": "ai_cli_test.sqlite3"}), encoding="utf-8")
    monkeypatch.delenv("DB_COLLECTOR_HOME", raising=False)
    monkeypatch.delenv("DB_COLLECTOR_DB_PATH", raising=False)
    return config_path


def _seed_page(config_path, runner) -> str:
    with responses.RequestsMock() as rsps:
        rsps.add(responses.GET, "https://example.jp/ramen/", body=_HTML, content_type="text/html")
        result = runner.invoke(main, ["--config", str(config_path), "ci", "analyze-lp", "https://example.jp/ramen/"])
    run_id = json.loads(result.output)["run"]["crawl_run_id"]
    from db_collector_os.config import load_config
    from db_collector_os.database import Database
    from db_collector_os.competitive_intelligence.repository.pages import PageRepository
    db = Database(load_config(str(config_path)).db_path)
    return PageRepository(db).list_for_run(run_id, limit=1)[0]["page_id"]


def test_ai_analyze_command(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path, monkeypatch)
    runner = CliRunner()
    page_id = _seed_page(config_path, runner)

    result = runner.invoke(main, ["--config", str(config_path), "ci", "ai-analyze", page_id])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["page_id"] == page_id
    assert 0 <= data["ai_citation_readiness_score"] <= 100
    assert data["ai_search_total_score"] is None
    assert data["organic_visibility_score"] is None


def test_ai_status_command(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path, monkeypatch)
    runner = CliRunner()
    page_id = _seed_page(config_path, runner)
    runner.invoke(main, ["--config", str(config_path), "ci", "ai-analyze", page_id])

    result = runner.invoke(main, ["--config", str(config_path), "ci", "ai-status", page_id])
    assert result.exit_code == 0
    assert json.loads(result.output)["page_id"] == page_id


def test_ai_status_command_errors_for_unanalyzed_page(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path, monkeypatch)
    runner = CliRunner()
    page_id = _seed_page(config_path, runner)

    result = runner.invoke(main, ["--config", str(config_path), "ci", "ai-status", page_id])
    assert result.exit_code == 1


def test_ai_recompute_command(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path, monkeypatch)
    runner = CliRunner()
    page_id = _seed_page(config_path, runner)
    runner.invoke(main, ["--config", str(config_path), "ci", "ai-analyze", page_id])

    result = runner.invoke(main, ["--config", str(config_path), "ci", "ai-recompute", page_id])
    assert result.exit_code == 0
    assert json.loads(result.output)["page_id"] == page_id


def test_existing_ci_commands_unaffected_by_ai_commands(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path, monkeypatch)
    runner = CliRunner()
    result = runner.invoke(main, ["--config", str(config_path), "ci", "--help"])
    assert result.exit_code == 0
    assert "ai-analyze" in result.output
    assert "analyze-lp" in result.output  # pre-existing command still present
