"""Functional test for scripts/_phase1_batch1_report.py: runs it as a real
subprocess (the same way scripts/_phase1_batch1_watch_and_report.sh
invokes it) against a throwaway DB, and checks both the human-readable
sections and the machine-parsed summary lines the watcher script greps for.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).parent.parent
REPORT_SCRIPT = REPO_ROOT / "scripts" / "_phase1_batch1_report.py"


def _setup_job(tmp_path: Path, job_id: str = "job_prod_figure_official_site") -> Path:
    home = tmp_path / "var"
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_path = config_dir / "default.yaml"
    config_path.write_text(
        yaml.safe_dump({"home_dir": str(home), "db_path": "report_test.sqlite3"}), encoding="utf-8"
    )

    sys.path.insert(0, str(REPO_ROOT))
    from db_collector_os.config import load_config
    from db_collector_os.database import Database
    from db_collector_os.job_registry import JobRegistry
    from db_collector_os.run_history import RunHistoryStore

    cfg = load_config(str(config_path))
    db = Database(cfg.db_path)
    jr = JobRegistry(db)
    jr.create(
        job_name="t", category="figure", target_db="d", target_table="entities",
        collector_type="official_site", adapter="figure_official_site", job_id=job_id,
    )
    rh = RunHistoryStore(db)
    run_id = rh.start(job_id)
    rh.finish(run_id, "completed", fetched_count=1, inserted_count=1, error_count=0)
    db.close()
    return tmp_path


def _run_report_script(cwd: Path, job_id: str) -> subprocess.CompletedProcess:
    python_bin = sys.executable
    return subprocess.run(
        [python_bin, str(REPORT_SCRIPT), job_id],
        cwd=str(cwd), capture_output=True, text=True, timeout=30,
    )


def test_report_script_success_case(tmp_path):
    job_id = "job_prod_figure_official_site"
    cwd = _setup_job(tmp_path, job_id)
    result = _run_report_script(cwd, job_id)
    assert result.returncode == 0, result.stderr
    assert "LATEST_RUN_ERROR_COUNT=0" in result.stdout
    assert "LATEST_RUN_STATUS=completed" in result.stdout
    assert "run_history" in result.stdout
    assert "checkpoint" in result.stdout


def test_report_script_unknown_job_still_runs_cleanly(tmp_path):
    cwd = _setup_job(tmp_path, "job_prod_figure_official_site")
    result = _run_report_script(cwd, "no_such_job")
    assert result.returncode == 0, result.stderr
    assert "LATEST_RUN_STATUS=none" in result.stdout
    assert "ENTITY_COUNT=0" in result.stdout


def test_report_script_requires_job_id_arg(tmp_path):
    cwd = _setup_job(tmp_path)
    result = subprocess.run(
        [sys.executable, str(REPORT_SCRIPT)], cwd=str(cwd), capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 2
    assert "usage" in result.stderr
