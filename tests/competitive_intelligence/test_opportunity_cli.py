from __future__ import annotations

import json
from pathlib import Path

import responses
import yaml
from click.testing import CliRunner

from db_collector_os.cli import main

_HTML_A = """<!doctype html><html><head><title>おすすめ 睡眠グッズまとめ</title>
<link rel="canonical" href="https://competitor-a.example/page/"></head><body>
<main><h1>おすすめ 睡眠グッズまとめ</h1><p>おすすめ 睡眠グッズについて簡単に紹介します。</p></main>
</body></html>"""

_HTML_OURS = """<!doctype html><html><head><title>おすすめ 睡眠グッズ【2026年最新・独自調査】</title>
<link rel="canonical" href="https://our-site.example/page/"></head><body>
<main><h1>おすすめ 睡眠グッズ【2026年最新版・独自調査】</h1>
<p>編集部が実際に80点を試し、独自調査・n=80のアンケート調査を実施した結果をもとに作成しました。
同ジャンル1,000点中上位1%です。レビュー数は300件から900件に増加しました。順位も25位から2位に上昇しています。
調査方法は覆面調査です。サンプルサイズはn=80です。価格帯・特徴も含めて徹底的に比較しています。</p>
<table><tr><th>商品</th><th>評価</th></tr><tr><td>A</td><td>4.8</td></tr></table>
</main></body></html>"""


def _write_config(tmp_path: Path, monkeypatch) -> Path:
    home = tmp_path / "var"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump({"home_dir": str(home), "db_path": "opportunity_cli_test.sqlite3"}),
                            encoding="utf-8")
    monkeypatch.delenv("DB_COLLECTOR_HOME", raising=False)
    monkeypatch.delenv("DB_COLLECTOR_DB_PATH", raising=False)
    return config_path


def _seed_page(config_path, runner, html, url) -> tuple[str, object]:
    with responses.RequestsMock() as rsps:
        rsps.add(responses.GET, url, body=html, content_type="text/html")
        result = runner.invoke(main, ["--config", str(config_path), "ci", "analyze-lp", url])
    assert result.exit_code == 0, result.output
    run_id = json.loads(result.output)["run"]["crawl_run_id"]
    from db_collector_os.config import load_config
    from db_collector_os.database import Database
    from db_collector_os.competitive_intelligence.repository.pages import PageRepository
    cfg = load_config(str(config_path))
    db = Database(cfg.db_path)
    page = PageRepository(db).list_for_run(run_id, limit=1)[0]
    db.close()
    return page["page_id"], cfg


def _run_ai_analyze(config_path, runner, page_id):
    result = runner.invoke(main, ["--config", str(config_path), "ci", "ai-analyze", page_id])
    assert result.exit_code == 0, result.output


def test_opportunity_page_command(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path, monkeypatch)
    runner = CliRunner()
    page_id, cfg = _seed_page(config_path, runner, _HTML_OURS, "https://our-site.example/page/")
    _run_ai_analyze(config_path, runner, page_id)

    result = runner.invoke(main, ["--config", str(config_path), "ci", "opportunity", "page", page_id])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["entity_type"] == "page"
    assert data["score_status"] in ("COMPLETE", "PARTIAL", "INTERNAL_ONLY", "NOT_ENOUGH_DATA")


def test_opportunity_keyword_requires_our_page_option(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path, monkeypatch)
    runner = CliRunner()
    result = runner.invoke(main, ["--config", str(config_path), "ci", "opportunity", "keyword", "some-keyword-id"])
    assert result.exit_code != 0
    assert "our-page" in result.output.lower() or "our_page" in result.output.lower() or "Missing option" in result.output


def test_opportunity_compare_command(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path, monkeypatch)
    runner = CliRunner()
    page_a_id, cfg = _seed_page(config_path, runner, _HTML_A, "https://competitor-a.example/page/")
    page_ours_id, _ = _seed_page(config_path, runner, _HTML_OURS, "https://our-site.example/page/")
    _run_ai_analyze(config_path, runner, page_a_id)
    _run_ai_analyze(config_path, runner, page_ours_id)

    result = runner.invoke(main, ["--config", str(config_path), "ci", "opportunity", "compare", page_ours_id, page_a_id])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert any(d["comparison_dimension"] == "organic_rank" for d in data)


def test_opportunity_list_and_recompute_commands(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path, monkeypatch)
    runner = CliRunner()
    page_id, cfg = _seed_page(config_path, runner, _HTML_OURS, "https://our-site.example/page/")
    _run_ai_analyze(config_path, runner, page_id)

    recompute_result = runner.invoke(main, ["--config", str(config_path), "ci", "opportunity", "recompute"])
    assert recompute_result.exit_code == 0, recompute_result.output
    summary = json.loads(recompute_result.output)
    assert "pages_computed" in summary

    list_result = runner.invoke(main, ["--config", str(config_path), "ci", "opportunity", "list"])
    assert list_result.exit_code == 0, list_result.output


def test_opportunity_import_demand_command(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path, monkeypatch)
    runner = CliRunner()
    demand_file = tmp_path / "demand.json"
    demand_file.write_text(json.dumps([
        {"query": "q1", "source": "manual", "observed_at": "2026-01-01", "search_volume": 500},
    ]), encoding="utf-8")
    result = runner.invoke(main, ["--config", str(config_path), "ci", "opportunity", "import-demand", str(demand_file)])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["imported"] == 1


def test_opportunity_export_command(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path, monkeypatch)
    runner = CliRunner()
    page_id, cfg = _seed_page(config_path, runner, _HTML_OURS, "https://our-site.example/page/")
    _run_ai_analyze(config_path, runner, page_id)
    runner.invoke(main, ["--config", str(config_path), "ci", "opportunity", "page", page_id])

    out_dir = tmp_path / "opp_out"
    result = runner.invoke(
        main, ["--config", str(config_path), "ci", "opportunity", "export", "--out-dir", str(out_dir)]
    )
    assert result.exit_code == 0, result.output
    assert (out_dir / "opportunities.csv").exists()
    assert (out_dir / "competitor_comparison.csv").exists()
    assert (out_dir / "content_gaps.csv").exists()
    # utf-8-sig BOM check -- never mojibake for Japanese text.
    content = (out_dir / "opportunities.csv").read_bytes()
    assert content.startswith(b"\xef\xbb\xbf")


def test_existing_ci_commands_still_work_after_opportunity_addition(tmp_path, monkeypatch):
    """spec: never break existing CLI commands."""
    config_path = _write_config(tmp_path, monkeypatch)
    runner = CliRunner()
    result = runner.invoke(main, ["--config", str(config_path), "ci", "list"])
    assert result.exit_code == 0, result.output
