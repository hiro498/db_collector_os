"""Functional test for scripts/_phase1_batch3_report.py: runs it as a real
subprocess (the same way scripts/_phase1_batch3_watch_and_report.sh
invokes it) against a throwaway DB, checking the batch #3-specific
additions: RUN_COUNT (this batch's own runs only, via RUN_COUNT_BEFORE),
LIFECYCLE_OK, and the aggregate FETCHED/INSERTED/UPDATED/ERROR totals for
just this batch's runs.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).parent.parent
REPORT_SCRIPT = REPO_ROOT / "scripts" / "_phase1_batch3_report.py"


def _setup_job(tmp_path: Path, job_id: str = "job_prod_figure_official_site", n_prior_runs: int = 1):
    home = tmp_path / "var"
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_path = config_dir / "default.yaml"
    config_path.write_text(
        yaml.safe_dump({"home_dir": str(home), "db_path": "report_test3.sqlite3"}), encoding="utf-8"
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
        config={"seed_urls": ["https://www.goodsmile.com/en/scalefigure_list", "https://www.goodsmile.com/en/product/1/x"]},
    )
    rh = RunHistoryStore(db)
    run_count_before = 0
    for _ in range(n_prior_runs):  # "prior" runs (before this batch) -- excluded from batch aggregates
        run_id = rh.start(job_id)
        rh.finish(run_id, "completed", fetched_count=1, inserted_count=1, error_count=0)
        run_count_before += 1

    # this batch's own runs: 3 separate run_history rows, all completed
    for fetched, inserted in ((10, 10), (10, 8), (5, 5)):
        run_id = rh.start(job_id)
        rh.finish(run_id, "completed", fetched_count=fetched, inserted_count=inserted, error_count=0)
    db.close()
    return tmp_path, run_count_before


def _run_report_script(cwd: Path, job_id: str, entity_count_before=None, run_count_before=None) -> subprocess.CompletedProcess:
    args = [sys.executable, str(REPORT_SCRIPT), job_id]
    if entity_count_before is not None:
        args.append(str(entity_count_before))
    if run_count_before is not None:
        args.append(str(run_count_before))
    return subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, timeout=30)


def test_run_count_and_batch_aggregates_exclude_prior_runs(tmp_path):
    job_id = "job_prod_figure_official_site"
    cwd, run_count_before = _setup_job(tmp_path, job_id, n_prior_runs=2)
    result = _run_report_script(cwd, job_id, entity_count_before=0, run_count_before=run_count_before)
    assert result.returncode == 0, result.stderr
    out = result.stdout

    assert "RUN_COUNT=3" in out  # only this batch's 3 runs, not the 2 prior ones
    assert "FETCHED_TOTAL_THIS_BATCH=25" in out  # 10+10+5, excludes the 2 prior runs' fetched=1 each
    assert "INSERTED_TOTAL_THIS_BATCH=23" in out  # 10+8+5
    assert "ERROR_TOTAL_THIS_BATCH=0" in out
    assert "NON_COMPLETED_RUNS_THIS_BATCH=0" in out
    assert "LIFECYCLE_OK=YES" in out
    # legacy BATCH_FETCHED/BATCH_INSERTED keys now reflect the batch aggregate too
    assert "BATCH_FETCHED=25" in out
    assert "BATCH_INSERTED=23" in out


def test_lifecycle_not_ok_when_a_batch_run_is_left_running(tmp_path):
    job_id = "job_prod_figure_official_site"
    cwd, run_count_before = _setup_job(tmp_path, job_id, n_prior_runs=0)

    sys.path.insert(0, str(REPO_ROOT))
    from db_collector_os.config import load_config
    from db_collector_os.database import Database

    config_path = cwd / "config" / "default.yaml"
    cfg = load_config(str(config_path))
    db = Database(cfg.db_path)
    # Leave one of this batch's runs stuck at 'running' (simulating a crash).
    row = db.query_one("SELECT run_id FROM run_history WHERE job_id=? ORDER BY started_at DESC LIMIT 1", (job_id,))
    db.execute("UPDATE run_history SET status='running' WHERE run_id=?", (row["run_id"],))
    db.close()

    result = _run_report_script(cwd, job_id, entity_count_before=0, run_count_before=run_count_before)
    assert result.returncode == 0, result.stderr
    assert "LIFECYCLE_OK=NO" in result.stdout
    assert "NON_COMPLETED_RUNS_THIS_BATCH=1" in result.stdout


def test_lifecycle_not_ok_when_status_left_as_retry_after_success(tmp_path):
    job_id = "job_prod_figure_official_site"
    cwd, run_count_before = _setup_job(tmp_path, job_id, n_prior_runs=0)

    sys.path.insert(0, str(REPO_ROOT))
    from db_collector_os.config import load_config
    from db_collector_os.database import Database

    config_path = cwd / "config" / "default.yaml"
    cfg = load_config(str(config_path))
    db = Database(cfg.db_path)
    db.execute("UPDATE jobs SET status='retry' WHERE job_id=?", (job_id,))
    db.close()

    result = _run_report_script(cwd, job_id, entity_count_before=0, run_count_before=run_count_before)
    assert result.returncode == 0, result.stderr
    assert "LIFECYCLE_OK=NO" in result.stdout  # error_total==0 but status=retry -- the exact reported bug


def test_report_script_requires_job_id_arg(tmp_path):
    cwd, _ = _setup_job(tmp_path)
    result = subprocess.run(
        [sys.executable, str(REPORT_SCRIPT)], cwd=str(cwd), capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 2
    assert "usage" in result.stderr
