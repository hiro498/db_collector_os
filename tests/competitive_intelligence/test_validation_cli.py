from __future__ import annotations

import json
from pathlib import Path

import responses
import yaml
from click.testing import CliRunner

from db_collector_os.cli import main

from .fixtures.affiliate_site import BASE, build_fixture_site


def _write_config(tmp_path: Path, monkeypatch) -> Path:
    home = tmp_path / "var"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump({"home_dir": str(home), "db_path": "validation_cli_test.sqlite3"}),
                            encoding="utf-8")
    monkeypatch.delenv("DB_COLLECTOR_HOME", raising=False)
    monkeypatch.delenv("DB_COLLECTOR_DB_PATH", raising=False)
    return config_path


def _register_fixture(rsps) -> None:
    pages = build_fixture_site()
    rsps.add(responses.GET, f"{BASE}/robots.txt", status=404)
    rsps.add(responses.GET, f"{BASE}/sitemap.xml", status=404)
    for url, html in pages.items():
        rsps.add(responses.GET, url, body=html, content_type="text/html")


def test_validate_domain_command_end_to_end(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path, monkeypatch)
    runner = CliRunner()
    out_dir = tmp_path / "out"

    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        _register_fixture(rsps)
        result = runner.invoke(main, [
            "--config", str(config_path), "ci", "validate-domain", f"{BASE}/",
            "--max-pages", "30", "--rate-limit", "100000", "--output-dir", str(out_dir),
        ])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["status"] == "COMPLETED"
    assert data["production_validation_status"] in ("PASS", "CONDITIONAL_PASS")
    for filename in (
        "summary.json", "pages.csv", "keywords_all.csv", "keywords_top100.csv", "target_keywords.csv",
        "content_map.csv", "opportunities.csv", "noise_audit.csv", "errors.csv",
    ):
        assert (out_dir / filename).exists(), f"missing output file: {filename}"


def test_validate_domain_defaults_to_30_pages_and_1_rps(tmp_path, monkeypatch):
    """spec section 6: MAX_PAGES defaults to 30 without explicit override."""
    config_path = _write_config(tmp_path, monkeypatch)
    runner = CliRunner()
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        _register_fixture(rsps)
        result = runner.invoke(main, [
            "--config", str(config_path), "ci", "validate-domain", f"{BASE}/", "--rate-limit", "100000",
        ])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["max_pages"] == 30


def test_validation_list_and_show_commands(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path, monkeypatch)
    runner = CliRunner()
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        _register_fixture(rsps)
        result = runner.invoke(main, [
            "--config", str(config_path), "ci", "validate-domain", f"{BASE}/", "--rate-limit", "100000",
        ])
    run_id = json.loads(result.output)["validation_run_id"]

    list_result = runner.invoke(main, ["--config", str(config_path), "ci", "validation", "list"])
    assert list_result.exit_code == 0, list_result.output
    assert run_id in list_result.output

    show_result = runner.invoke(main, ["--config", str(config_path), "ci", "validation", "show", run_id])
    assert show_result.exit_code == 0, show_result.output
    assert json.loads(show_result.output)["validation_run_id"] == run_id


def test_validation_show_unknown_run_exits_nonzero(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path, monkeypatch)
    runner = CliRunner()
    result = runner.invoke(main, ["--config", str(config_path), "ci", "validation", "show", "no-such-run"])
    assert result.exit_code != 0


def test_validation_export_command(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path, monkeypatch)
    runner = CliRunner()
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        _register_fixture(rsps)
        result = runner.invoke(main, [
            "--config", str(config_path), "ci", "validate-domain", f"{BASE}/", "--rate-limit", "100000",
        ])
    run_id = json.loads(result.output)["validation_run_id"]

    out_dir = tmp_path / "export_out"
    export_result = runner.invoke(
        main, ["--config", str(config_path), "ci", "validation", "export", run_id, "--out-dir", str(out_dir)]
    )
    assert export_result.exit_code == 0, export_result.output
    assert (out_dir / "target_keywords.csv").exists()
    content = (out_dir / "target_keywords.csv").read_bytes()
    assert content.startswith(b"\xef\xbb\xbf")


def test_validation_audit_command(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path, monkeypatch)
    runner = CliRunner()
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        _register_fixture(rsps)
        result = runner.invoke(main, [
            "--config", str(config_path), "ci", "validate-domain", f"{BASE}/", "--rate-limit", "100000",
        ])
    run_id = json.loads(result.output)["validation_run_id"]

    from db_collector_os.config import load_config
    from db_collector_os.database import Database
    from db_collector_os.competitive_intelligence.validation.repository import DomainKeywordSummaryRepository
    cfg = load_config(str(config_path))
    db = Database(cfg.db_path)
    sample = next(k for k in DomainKeywordSummaryRepository(db).list_for_run(run_id) if not k["is_noise"])
    db.close()

    audit_result = runner.invoke(main, [
        "--config", str(config_path), "ci", "validation", "audit", run_id, sample["normalized_keyword"],
        "--class", "A", "--note", "confirmed",
    ])
    assert audit_result.exit_code == 0, audit_result.output


def test_validation_audit_unknown_keyword_exits_nonzero(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path, monkeypatch)
    runner = CliRunner()
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        _register_fixture(rsps)
        result = runner.invoke(main, [
            "--config", str(config_path), "ci", "validate-domain", f"{BASE}/", "--rate-limit", "100000",
        ])
    run_id = json.loads(result.output)["validation_run_id"]
    audit_result = runner.invoke(main, [
        "--config", str(config_path), "ci", "validation", "audit", run_id, "no-such-keyword", "--class", "A",
    ])
    assert audit_result.exit_code != 0


def test_existing_ci_commands_unaffected_by_validation_addition(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path, monkeypatch)
    runner = CliRunner()
    result = runner.invoke(main, ["--config", str(config_path), "ci", "list"])
    assert result.exit_code == 0, result.output
    opp_result = runner.invoke(main, ["--config", str(config_path), "ci", "opportunity", "list"])
    assert opp_result.exit_code == 0, opp_result.output
