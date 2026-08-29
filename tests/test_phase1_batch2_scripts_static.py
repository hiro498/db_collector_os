"""Static assertions over the Phase 1 batch #2 VPS scripts' text -- the
same category of checks as test_phase1_batch1_scripts_static.py, applied
to the new batch #2 scripts, plus the batch #2-specific requirements: it
must reuse batch #1's safety design, batch #1 must be left untouched, and
the PHASE1_RESULT gate/report must cover the fields the task's VPS report
requirement lists.
"""

from __future__ import annotations

import re
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
MAIN_SCRIPT = (SCRIPTS_DIR / "run_goodsmile_phase1_batch2.sh").read_text(encoding="utf-8")
WATCH_SCRIPT = (SCRIPTS_DIR / "_phase1_batch2_watch_and_report.sh").read_text(encoding="utf-8")
BATCH1_MAIN_SCRIPT = (SCRIPTS_DIR / "run_goodsmile_phase1_batch1.sh").read_text(encoding="utf-8")


def test_batch1_script_untouched_as_history():
    assert (SCRIPTS_DIR / "run_goodsmile_phase1_batch1.sh").exists()
    assert (SCRIPTS_DIR / "_phase1_batch1_watch_and_report.sh").exists()
    assert (SCRIPTS_DIR / "_phase1_batch1_report.py").exists()
    assert "db_collector_phase1_batch1_goodsmile" in BATCH1_MAIN_SCRIPT


def test_no_shell_terminating_commands_at_top_level():
    for bad in (r"^\s*exit\b", r"^\s*logout\b", r"^\s*reboot\b", r"^\s*shutdown\b", r"exec\s+ssh"):
        assert not re.search(bad, MAIN_SCRIPT, re.MULTILINE), f"found forbidden `{bad}` in batch2 main script"


def test_main_script_never_disconnects_or_double_launches():
    assert "db_collector_phase1_batch2_goodsmile() {" in MAIN_SCRIPT
    assert MAIN_SCRIPT.rstrip().endswith("db_collector_phase1_batch2_goodsmile")
    assert "systemd-run" in MAIN_SCRIPT
    assert 'systemctl is-active --quiet "$WATCH_UNIT.service"' in MAIN_SCRIPT  # double-launch guard
    assert "db-collector-phase1-batch2-goodsmile" in MAIN_SCRIPT
    assert "db-collector-phase1-batch1-goodsmile" not in MAIN_SCRIPT  # distinct unit name from batch1


def test_main_script_has_full_precheck_sequence():
    required_markers = [
        "git status --short",
        "git fetch origin --prune",
        "git merge --ff-only",
        '"$CLI" migrate',
        "backup.sh",
        '"$CLI" integrity',
        "compileall",
        "worker reload",
        "services active",
        "Admin UI HTTP 200",
        "resource gate",
        "robots.txt",
        "sample jobs disabled",
        '"$CLI" jobs sync',
        '"$CLI" jobs reseed "$JOB_ID"',
        '"$CLI" jobs enable "$JOB_ID"',
        '"$CLI" jobs resume "$JOB_ID"',
    ]
    for marker in required_markers:
        assert marker in MAIN_SCRIPT, f"missing precheck/flow marker: {marker!r}"

    # order matters: sync -> reseed -> enable -> resume
    sync_idx = MAIN_SCRIPT.index('"$CLI" jobs sync')
    reseed_idx = MAIN_SCRIPT.index('"$CLI" jobs reseed "$JOB_ID"')
    enable_idx = MAIN_SCRIPT.index('"$CLI" jobs enable "$JOB_ID"')
    resume_idx = MAIN_SCRIPT.index('"$CLI" jobs resume "$JOB_ID"')
    assert sync_idx < reseed_idx < enable_idx < resume_idx


def test_main_script_captures_entity_count_before_and_passes_to_watcher():
    assert "ENTITY_COUNT_BEFORE" in MAIN_SCRIPT
    assert "--setenv=PHASE1_ENTITY_COUNT_BEFORE=" in MAIN_SCRIPT
    assert "--setenv=PHASE1_PREVIOUS_LATEST_RUN_ID=" in MAIN_SCRIPT


def test_main_script_never_touches_resource_thresholds_or_swap():
    # The script only ever *reads* resource_thresholds via ResourceController
    # (cfg.resource_thresholds passed straight into it) -- never assigns to
    # it or otherwise mutates host resource configuration.
    assert not re.search(r"resource_thresholds\s*=", MAIN_SCRIPT)
    assert "swapoff" not in MAIN_SCRIPT
    assert "ResourceController(cfg.resource_thresholds)" in MAIN_SCRIPT


def test_main_script_never_overrides_concurrency_or_rate_limit():
    # concurrency/rate_limit come from the job YAML via `jobs sync` -- this
    # script must never set/override them directly.
    assert not re.search(r"\bconcurrency\s*=\s*[2-9]", MAIN_SCRIPT)
    assert "UPDATE jobs SET concurrency" not in MAIN_SCRIPT
    assert "UPDATE jobs SET rate_limit" not in MAIN_SCRIPT


def test_watch_script_computes_phase1_result_pass_partial_fail():
    assert "PHASE1_RESULT=PASS" in WATCH_SCRIPT
    assert "PHASE1_RESULT=PARTIAL" in WATCH_SCRIPT
    assert "PHASE1_RESULT=FAIL" in WATCH_SCRIPT
    # PASS bar: entity delta > 0, inserted > 0, fetched > 1 -- re-fetching a
    # single already-known entity must not be reported PASS.
    assert "entity_delta_not_gt_0" in WATCH_SCRIPT
    assert "inserted_count_not_gt_0" in WATCH_SCRIPT
    assert "fetched_count_not_gt_1" in WATCH_SCRIPT


def test_watch_script_disables_job_and_reports_run_lifecycle_gate():
    assert "RUN_LIFECYCLE_GATE" in WATCH_SCRIPT
    assert "PRODUCTION_JOB_DISABLED_AFTER_BATCH=YES" in WATCH_SCRIPT
    assert '"$CLI" jobs disable "$JOB_ID"' in WATCH_SCRIPT


def test_watch_script_uses_batch2_report_script():
    assert "_phase1_batch2_report.py" in WATCH_SCRIPT
    assert "ENTITY_COUNT_BEFORE" in WATCH_SCRIPT
