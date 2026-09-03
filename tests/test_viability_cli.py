from __future__ import annotations

import json
from pathlib import Path

import yaml
from click.testing import CliRunner

from db_collector_os.cli import main


def _write_config(tmp_path: Path) -> Path:
    home = tmp_path / "var"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump({"home_dir": str(home), "db_path": "cli_test.sqlite3"}), encoding="utf-8")
    return config_path


def test_viability_full_cli_flow(tmp_path, monkeypatch):
    for key in ("DB_COLLECTOR_HOME", "DB_COLLECTOR_DB_PATH", "DB_COLLECTOR_VIABILITY_CONFIG"):
        monkeypatch.delenv(key, raising=False)
    config_path = _write_config(tmp_path)
    runner = CliRunner()

    assert runner.invoke(main, ["--config", str(config_path), "migrate"]).exit_code == 0

    result = runner.invoke(main, ["--config", str(config_path), "viability", "idea", "create", "--theme", "CLIテーマ"])
    assert result.exit_code == 0, result.output
    idea_id = result.output.strip()

    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(
        yaml.safe_dump({"main_keywords": ["メインKW"], "axes": {"region": ["東京", "埼玉", "大阪"]}}),
        encoding="utf-8",
    )
    result = runner.invoke(main, ["--config", str(config_path), "viability", "keywords", "generate", idea_id, "--spec", str(spec_path)])
    assert result.exit_code == 0, result.output

    metrics_csv = tmp_path / "metrics.csv"
    metrics_csv.write_text(
        "keyword,monthly_search_volume\n"
        "メインKW,500\n東京 メインKW,120\nメインKW 東京,80\n埼玉 メインKW,60\nメインKW 埼玉,40\n大阪 メインKW,30\nメインKW 大阪,20\n",
        encoding="utf-8",
    )
    result = runner.invoke(main, ["--config", str(config_path), "viability", "metrics", "import-csv", idea_id, str(metrics_csv)])
    assert result.exit_code == 0, result.output

    result = runner.invoke(main, ["--config", str(config_path), "viability", "phase1-run", idea_id])
    assert result.exit_code == 0, result.output
    phase1 = json.loads(result.output)
    assert phase1["phase1_result"] == "PASS"
    run_id = phase1["run_id"]

    serp_csv = tmp_path / "serp.csv"
    serp_csv.write_text(
        "query,rank,title,url,site_type,page_type,db_type_page,intent_satisfied\n"
        "東京 メインKW,1,ブログ記事,https://blog.example/a,personal,article,false,false\n",
        encoding="utf-8",
    )
    result = runner.invoke(
        main, ["--config", str(config_path), "viability", "serp", "import-csv", run_id, idea_id, str(serp_csv)]
    )
    assert result.exit_code == 0, result.output

    result = runner.invoke(main, ["--config", str(config_path), "viability", "phase2-run", run_id])
    assert result.exit_code == 0, result.output

    result = runner.invoke(main, ["--config", str(config_path), "viability", "evaluate", run_id])
    assert result.exit_code == 0, result.output
    evaluation = json.loads(result.output)
    assert evaluation["final_judgement"] in ("GO", "HOLD", "NO-GO")

    result = runner.invoke(main, ["--config", str(config_path), "viability", "report", idea_id])
    assert result.exit_code == 0, result.output
    assert "最終判定" in result.output

    result = runner.invoke(main, ["--config", str(config_path), "viability", "runs-list", idea_id])
    assert result.exit_code == 0
    assert run_id in result.output


def test_viability_idea_list_and_show(tmp_path, monkeypatch):
    for key in ("DB_COLLECTOR_HOME", "DB_COLLECTOR_DB_PATH"):
        monkeypatch.delenv(key, raising=False)
    config_path = _write_config(tmp_path)
    runner = CliRunner()
    runner.invoke(main, ["--config", str(config_path), "migrate"])

    result = runner.invoke(main, ["--config", str(config_path), "viability", "idea", "create", "--theme", "T"])
    idea_id = result.output.strip()

    result = runner.invoke(main, ["--config", str(config_path), "viability", "idea", "list"])
    assert idea_id in result.output

    result = runner.invoke(main, ["--config", str(config_path), "viability", "idea", "show", idea_id])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["theme_name"] == "T"
