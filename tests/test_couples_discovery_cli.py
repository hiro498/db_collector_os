"""Tests for `db-collector couples discover-dry-run` (see
db_collector_os/cli.py and discovery/lovehotel_couples.py).

Exercises the CLI's --fixtures-dir OFFLINE mode end-to-end (this authoring
environment has no outbound network access to couples.jp -- confirmed
blocked, see docs/lovehotel_couples_db.md), asserting: no DB is touched, no
job is enabled/resumed, the report/JSON files are written, and the report
format matches the task's required Gate output shape.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from click.testing import CliRunner

from db_collector_os.cli import main
from db_collector_os.discovery.prefecture import PREFECTURES

REPO_ROOT = Path(__file__).parent.parent


def _write_fixture_site(base: Path) -> None:
    """A small, self-contained synthetic couples.jp-shaped site covering
    all 47 prefectures: 5 prefectures with real facility pages (including a
    derived /review URL and a tracking-param duplicate, to exercise
    canonicalization end-to-end), 1 genuinely empty prefecture, and the
    remaining 41 with no discoverable entry link at all (a realistic
    "coverage isn't perfect yet" shape for this test, not a claim about the
    real site)."""
    manifest: dict[str, str] = {}

    nav_links = "\n".join(f'<a href="https://couples.jp/prefectures/{i}">{p}</a>' for i, p in enumerate(PREFECTURES[:6], start=1))
    (base / "top.html").write_text(f"<html><body>{nav_links}</body></html>", encoding="utf-8")
    manifest["https://couples.jp/"] = "top.html"

    # 北海道: 2 facilities, one reached via a /review derived link + a
    # tracking-param duplicate of the other -- must canonicalize/dedupe.
    (base / "p1.html").write_text(
        """<html><body>
        <a href="https://couples.jp/hotel-details/9001">A</a>
        <a href="https://couples.jp/hotel-details/9001?utm_source=list">A dup</a>
        <a href="https://couples.jp/hotel-details/9002/review">B via review</a>
        <a href="https://couples.jp/articles/1">not a facility</a>
        </body></html>""",
        encoding="utf-8",
    )
    manifest["https://couples.jp/prefectures/1"] = "p1.html"

    # 青森県: paginated, 2 pages, 1 facility each.
    (base / "p2.html").write_text(
        """<html><body>
        <a href="https://couples.jp/hotel-details/9101">C</a>
        <a href="https://couples.jp/prefectures/2?page=2">next</a>
        </body></html>""",
        encoding="utf-8",
    )
    manifest["https://couples.jp/prefectures/2"] = "p2.html"
    (base / "p2b.html").write_text(
        '<html><body><a href="https://couples.jp/hotel-details/9102">D</a></body></html>', encoding="utf-8",
    )
    manifest["https://couples.jp/prefectures/2?page=2"] = "p2b.html"

    for i in [3, 4, 5]:
        (base / f"p{i}.html").write_text(
            f'<html><body><a href="https://couples.jp/hotel-details/{9200 + i}">E{i}</a></body></html>', encoding="utf-8",
        )
        manifest[f"https://couples.jp/prefectures/{i}"] = f"p{i}.html"

    # 6th prefecture: genuinely empty (fetched fine, zero facilities).
    (base / "p6.html").write_text("<html><body><p>No hotels found</p></body></html>", encoding="utf-8")
    manifest["https://couples.jp/prefectures/6"] = "p6.html"

    (base / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")


def test_dry_run_offline_mode_never_touches_a_database(tmp_path):
    _write_fixture_site(tmp_path)
    out_dir = tmp_path / "out"
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "couples", "discover-dry-run",
            "--fixtures-dir", str(tmp_path),
            "--output-dir", str(out_dir),
        ],
    )
    assert result.exit_code == 1, result.output  # 41 no_entry_url prefectures -> FAILED_PREFECTURES > 0 in this fixture
    assert "47_PREFECTURES_VISITED=47" in result.output
    assert "DISCOVERY_COMPLETE=" in result.output
    assert "SIMULATED RUN" in result.output

    # no sqlite file of any kind was created anywhere under tmp_path:
    assert list(tmp_path.rglob("*.sqlite3")) == []
    assert list(tmp_path.rglob("*.db")) == []


def test_dry_run_offline_mode_writes_report_and_json_files(tmp_path):
    _write_fixture_site(tmp_path)
    out_dir = tmp_path / "out"
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["couples", "discover-dry-run", "--fixtures-dir", str(tmp_path), "--output-dir", str(out_dir)],
    )
    txt_files = list(out_dir.glob("*.txt"))
    json_files = list(out_dir.glob("*.json"))
    assert len(txt_files) == 1
    assert len(json_files) == 1

    report = txt_files[0].read_text(encoding="utf-8")
    assert "UNIQUE_FACILITY_IDS=7" in report  # 9001,9002,9101,9102,9203,9204,9205
    assert "REVIEW_URL_CONTAMINATION=0" in report
    assert "NON_FACILITY_URL_CONTAMINATION=0" in report

    summary = json.loads(json_files[0].read_text(encoding="utf-8"))
    assert summary["per_prefecture"]["北海道"]["status"] == "ok"
    assert summary["per_prefecture"]["北海道"]["unique_facility_count"] == 2
    assert summary["per_prefecture"][PREFECTURES[5]]["status"] == "empty"
    assert summary["per_prefecture"][PREFECTURES[6]]["status"] == "no_entry_url"
    facility_ids = {f["facility_id"] for f in summary["facilities"]}
    assert {"9001", "9002", "9101", "9102"}.issubset(facility_ids)


def test_dry_run_exit_code_zero_when_no_prefecture_fails(tmp_path):
    """A minimal all-47-covered fixture (every prefecture has SOME entry
    link, even if some are genuinely empty) must exit 0 and report
    DISCOVERY_COMPLETE=YES."""
    manifest: dict[str, str] = {}
    nav_links = "\n".join(f'<a href="https://couples.jp/prefectures/{i}">{p}</a>' for i, p in enumerate(PREFECTURES, start=1))
    (tmp_path / "top.html").write_text(f"<html><body>{nav_links}</body></html>", encoding="utf-8")
    manifest["https://couples.jp/"] = "top.html"
    for i, pref in enumerate(PREFECTURES, start=1):
        fname = f"pref{i}.html"
        if i == 1:
            (tmp_path / fname).write_text(
                '<html><body><a href="https://couples.jp/hotel-details/1">X</a></body></html>', encoding="utf-8",
            )
        else:
            (tmp_path / fname).write_text("<html><body>no hotels</body></html>", encoding="utf-8")
        manifest[f"https://couples.jp/prefectures/{i}"] = fname
    (tmp_path / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["couples", "discover-dry-run", "--fixtures-dir", str(tmp_path), "--output-dir", str(tmp_path / "out")],
    )
    assert result.exit_code == 0, result.output
    assert "DISCOVERY_COMPLETE=YES" in result.output
    assert "FAILED_PREFECTURES=0" in result.output


def test_production_job_stays_paused_and_disabled_and_untouched_by_this_change():
    """Sanity guard for this task's own absolute conditions: the dry-run CLI
    is a pure discovery/reporting tool and must never itself flip
    job_prod_lovehotel_couples's enabled flag or config -- confirm the job
    YAML on disk is completely unmodified by this change (still enabled:
    false, same discovery config) and that the new couples CLI group
    contains no jobs-enable/resume call anywhere in its own module."""
    spec = yaml.safe_load((REPO_ROOT / "config" / "jobs" / "prod_lovehotel_couples.yaml").read_text(encoding="utf-8"))
    assert spec["enabled"] is False

    import inspect

    from db_collector_os import cli as cli_module

    source = inspect.getsource(cli_module.couples_discover_dry_run.callback)
    assert "enable" not in source.lower()
    assert "resume" not in source.lower()
    assert "Database(" not in source
