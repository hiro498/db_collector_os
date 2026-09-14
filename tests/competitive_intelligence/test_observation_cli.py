from __future__ import annotations

import json
from pathlib import Path

import responses
import yaml
from click.testing import CliRunner

from db_collector_os.cli import main

_HTML = """<!doctype html><html><head><title>t</title>
<link rel="canonical" href="https://example.jp/ramen/"></head><body>
<main><h1>渋谷ラーメンおすすめランキング</h1><p>編集部が実際に調査した結果、同ジャンル100件中上位5%です。</p></main>
</body></html>"""


def _write_config(tmp_path: Path, monkeypatch) -> Path:
    home = tmp_path / "var"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump({"home_dir": str(home), "db_path": "observation_cli_test.sqlite3"}),
                            encoding="utf-8")
    monkeypatch.delenv("DB_COLLECTOR_HOME", raising=False)
    monkeypatch.delenv("DB_COLLECTOR_DB_PATH", raising=False)
    return config_path


def _seed_page(config_path, runner) -> str:
    with responses.RequestsMock() as rsps:
        rsps.add(responses.GET, "https://example.jp/ramen/", body=_HTML, content_type="text/html")
        result = runner.invoke(main, ["--config", str(config_path), "ci", "analyze-lp", "https://example.jp/ramen/"])
    assert result.exit_code == 0, result.output
    run_id = json.loads(result.output)["run"]["crawl_run_id"]
    from db_collector_os.config import load_config
    from db_collector_os.database import Database
    from db_collector_os.competitive_intelligence.repository.pages import PageRepository
    db = Database(load_config(str(config_path)).db_path)
    page_id = PageRepository(db).list_for_run(run_id, limit=1)[0]["page_id"]
    db.close()
    return page_id


def test_observation_status_on_empty_db(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path, monkeypatch)
    runner = CliRunner()
    result = runner.invoke(main, ["--config", str(config_path), "ci", "observation", "status"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["serp_observations"] == 0
    assert data["pages_with_visibility_computed"] == 0


def test_observation_import_and_show(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path, monkeypatch)
    runner = CliRunner()
    page_id = _seed_page(config_path, runner)

    import_file = tmp_path / "organic.json"
    import_file.write_text(json.dumps([
        {"query": "渋谷 ラーメン", "country": "JP", "language": "ja", "device": "desktop",
         "observed_at": "2026-01-01T00:00:00Z", "provider": "manual",
         "results": [{"result_position": 4, "result_url": "https://example.jp/ramen/"}]},
    ]), encoding="utf-8")

    result = runner.invoke(
        main, ["--config", str(config_path), "ci", "observation", "import", str(import_file),
               "--type", "organic", "--provider", "manual"],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["status"] == "imported"

    list_result = runner.invoke(main, ["--config", str(config_path), "ci", "observation", "list"])
    assert result.exit_code == 0
    assert "type=organic" in list_result.output

    show_before = runner.invoke(main, ["--config", str(config_path), "ci", "observation", "show", page_id])
    assert show_before.exit_code == 1

    show_after = runner.invoke(
        main, ["--config", str(config_path), "ci", "observation", "show", page_id, "--recompute"],
    )
    assert show_after.exit_code == 0, show_after.output
    data = json.loads(show_after.output)
    assert data["organic_rank"] == 4
    assert data["aio_cited"] is None


def test_observe_commands_never_crash_and_report_unavailable(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path, monkeypatch)
    runner = CliRunner()
    for surface in ("organic", "aio", "ai-mode", "fanout"):
        result = runner.invoke(main, ["--config", str(config_path), "ci", "observe", surface, "test query"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["status"] == "unavailable"
        assert data["surface"] == surface
