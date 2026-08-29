"""Functional test for scripts/_phase1_batch2_report.py: runs it as a real
subprocess (the same way scripts/_phase1_batch2_watch_and_report.sh
invokes it) against a throwaway DB, and checks both the human-readable
sections and the machine-parsed summary lines (including the batch #2
additions: SEED_URL_COUNT, DISCOVERED_URL_COUNT, QUEUE_*, ENTITY_COUNT_
BEFORE/AFTER/DELTA, HTTP_2XX/3XX/4XX/5XX, REVIEW_OPEN, CHECKPOINT) the
watcher script greps for.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).parent.parent
REPORT_SCRIPT = REPO_ROOT / "scripts" / "_phase1_batch2_report.py"


def _setup_job(tmp_path: Path, job_id: str = "job_prod_figure_official_site") -> Path:
    home = tmp_path / "var"
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_path = config_dir / "default.yaml"
    config_path.write_text(
        yaml.safe_dump({"home_dir": str(home), "db_path": "report_test2.sqlite3"}), encoding="utf-8"
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
    run_id = rh.start(job_id)
    rh.finish(run_id, "completed", fetched_count=5, inserted_count=4, discovered_count=6, error_count=0)
    db.close()
    return tmp_path


def _run_report_script(cwd: Path, job_id: str, entity_count_before: int | None = None) -> subprocess.CompletedProcess:
    args = [sys.executable, str(REPORT_SCRIPT), job_id]
    if entity_count_before is not None:
        args.append(str(entity_count_before))
    return subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, timeout=30)


def test_report_script_success_case_with_entity_count_before(tmp_path):
    job_id = "job_prod_figure_official_site"
    cwd = _setup_job(tmp_path, job_id)
    result = _run_report_script(cwd, job_id, entity_count_before=1)
    assert result.returncode == 0, result.stderr
    out = result.stdout

    assert "JOB_ID=job_prod_figure_official_site" in out
    assert "RUN_ID=" in out
    assert "STATUS=" in out
    assert "PHASE=" in out
    assert "ENABLED=" in out
    assert "SEED_URL_COUNT=2" in out
    assert "DISCOVERED_URL_COUNT=" in out
    assert "QUEUE_TOTAL=" in out
    assert "QUEUE_PENDING=" in out
    assert "QUEUE_FETCHED=" in out
    assert "QUEUE_FAILED=" in out
    assert "FETCHED_COUNT=5" in out
    assert "INSERTED_COUNT=4" in out
    assert "UPDATED_COUNT=0" in out
    assert "ERROR_COUNT=0" in out
    assert "ENTITY_COUNT_BEFORE=1" in out
    assert "ENTITY_COUNT_AFTER=0" in out  # no entity rows created in this throwaway setup
    assert "ENTITY_DELTA=-1" in out
    assert "EVIDENCE_COUNT=" in out
    assert "HTTP_2XX=" in out
    assert "HTTP_3XX=" in out
    assert "HTTP_4XX=" in out
    assert "HTTP_5XX=" in out
    assert "REVIEW_OPEN=" in out
    assert "CHECKPOINT=" in out
    assert "CHECKPOINT_PHASE=" in out


def test_report_script_without_entity_count_before_arg_still_runs(tmp_path):
    job_id = "job_prod_figure_official_site"
    cwd = _setup_job(tmp_path, job_id)
    result = _run_report_script(cwd, job_id)
    assert result.returncode == 0, result.stderr
    assert "ENTITY_COUNT_BEFORE=unknown" in result.stdout
    assert "ENTITY_DELTA=unknown" in result.stdout


def test_report_script_unknown_job_still_runs_cleanly(tmp_path):
    cwd = _setup_job(tmp_path)
    result = _run_report_script(cwd, "no_such_job", entity_count_before=0)
    assert result.returncode == 0, result.stderr
    assert "LATEST_RUN_STATUS=none" in result.stdout
    assert "ENTITY_COUNT=0" in result.stdout
    assert "SEED_URL_COUNT=0" in result.stdout


def test_report_script_requires_job_id_arg(tmp_path):
    cwd = _setup_job(tmp_path)
    result = subprocess.run(
        [sys.executable, str(REPORT_SCRIPT)], cwd=str(cwd), capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 2
    assert "usage" in result.stderr
