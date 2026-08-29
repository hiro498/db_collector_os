"""Static assertions over the Phase 1 batch #3 VPS scripts' text -- the
same category of checks as test_phase1_batch1/2_scripts_static.py, applied
to the new batch #3 scripts, plus the batch #3-specific requirements: it
reuses batch #1/#2's safety design unchanged, batch #1/#2 are left
untouched, the job's final status is never left as 'continuing'/'retry'
(disable AND pause), and no script anywhere performs a destructive DB
operation against production data.
"""

from __future__ import annotations

import re
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
MAIN_SCRIPT = (SCRIPTS_DIR / "run_goodsmile_phase1_batch3.sh").read_text(encoding="utf-8")
WATCH_SCRIPT = (SCRIPTS_DIR / "_phase1_batch3_watch_and_report.sh").read_text(encoding="utf-8")
BATCH1_MAIN_SCRIPT = (SCRIPTS_DIR / "run_goodsmile_phase1_batch1.sh").read_text(encoding="utf-8")
BATCH2_MAIN_SCRIPT = (SCRIPTS_DIR / "run_goodsmile_phase1_batch2.sh").read_text(encoding="utf-8")

DESTRUCTIVE_SQL_RE = re.compile(
    r"\b(DELETE\s+FROM|DROP\s+TABLE|TRUNCATE|UPDATE\s+entities\b|UPDATE\s+evidence\b)", re.IGNORECASE
)


def test_batch1_and_batch2_scripts_untouched_as_history():
    for name in (
        "run_goodsmile_phase1_batch1.sh", "_phase1_batch1_watch_and_report.sh", "_phase1_batch1_report.py",
        "run_goodsmile_phase1_batch2.sh", "_phase1_batch2_watch_and_report.sh", "_phase1_batch2_report.py",
    ):
        assert (SCRIPTS_DIR / name).exists()
    assert "db_collector_phase1_batch1_goodsmile" in BATCH1_MAIN_SCRIPT
    assert "db_collector_phase1_batch2_goodsmile" in BATCH2_MAIN_SCRIPT


def test_no_shell_terminating_commands_at_top_level():
    for bad in (r"^\s*exit\b", r"^\s*logout\b", r"^\s*reboot\b", r"^\s*shutdown\b", r"exec\s+ssh"):
        assert not re.search(bad, MAIN_SCRIPT, re.MULTILINE), f"found forbidden `{bad}` in batch3 main script"


def test_main_script_never_disconnects_or_double_launches():
    assert "db_collector_phase1_batch3_goodsmile() {" in MAIN_SCRIPT
    assert MAIN_SCRIPT.rstrip().endswith("db_collector_phase1_batch3_goodsmile")
    assert "systemd-run" in MAIN_SCRIPT
    assert 'systemctl is-active --quiet "$WATCH_UNIT.service"' in MAIN_SCRIPT
    assert "db-collector-phase1-batch3-goodsmile" in MAIN_SCRIPT
    assert "db-collector-phase1-batch1-goodsmile" not in MAIN_SCRIPT
    assert "db-collector-phase1-batch2-goodsmile" not in MAIN_SCRIPT


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
        "no other production job enabled",
        '"$CLI" jobs sync',
        '"$CLI" jobs reseed "$JOB_ID"',
        '"$CLI" jobs enable "$JOB_ID"',
        '"$CLI" jobs resume "$JOB_ID"',
    ]
    for marker in required_markers:
        assert marker in MAIN_SCRIPT, f"missing precheck/flow marker: {marker!r}"

    sync_idx = MAIN_SCRIPT.index('"$CLI" jobs sync')
    reseed_idx = MAIN_SCRIPT.index('"$CLI" jobs reseed "$JOB_ID"')
    enable_idx = MAIN_SCRIPT.index('"$CLI" jobs enable "$JOB_ID"')
    resume_idx = MAIN_SCRIPT.index('"$CLI" jobs resume "$JOB_ID"')
    assert sync_idx < reseed_idx < enable_idx < resume_idx


def test_main_script_captures_run_count_and_queue_pending_before():
    assert "RUN_COUNT_BEFORE" in MAIN_SCRIPT
    assert "QUEUE_PENDING_BEFORE" in MAIN_SCRIPT
    assert "ENTITY_COUNT_BEFORE" in MAIN_SCRIPT
    assert "--setenv=PHASE1_RUN_COUNT_BEFORE=" in MAIN_SCRIPT
    assert "--setenv=PHASE1_QUEUE_PENDING_BEFORE=" in MAIN_SCRIPT
    assert "--setenv=PHASE1_ENTITY_COUNT_BEFORE=" in MAIN_SCRIPT
    assert "--setenv=PHASE1_PREVIOUS_LATEST_RUN_ID=" in MAIN_SCRIPT


def test_main_script_never_overrides_concurrency_or_rate_limit():
    assert not re.search(r"\bconcurrency\s*=\s*[2-9]", MAIN_SCRIPT)
    assert "UPDATE jobs SET concurrency" not in MAIN_SCRIPT
    assert "UPDATE jobs SET rate_limit" not in MAIN_SCRIPT


def test_watch_script_computes_lifecycle_ok_and_phase1_result():
    assert "LIFECYCLE_OK" in WATCH_SCRIPT
    assert "RUN_COUNT" in WATCH_SCRIPT
    assert "PHASE1_RESULT=PASS" in WATCH_SCRIPT
    assert "PHASE1_RESULT=PARTIAL" in WATCH_SCRIPT
    assert "PHASE1_RESULT=FAIL" in WATCH_SCRIPT
    assert "lifecycle_not_ok" in WATCH_SCRIPT
    assert "runaway_one_page_per_run" in WATCH_SCRIPT
    # batch #3 explicitly does NOT require entity_delta>0 for PASS/FAIL --
    # only informational for PARTIAL.
    assert "entity_delta_not_gt_0" not in WATCH_SCRIPT.split("PARTIAL_REASONS=\"\"")[0]


def test_watch_script_disables_and_pauses_job_never_leaving_retry():
    assert '"$CLI" jobs disable "$JOB_ID"' in WATCH_SCRIPT
    assert '"$CLI" jobs pause "$JOB_ID"' in WATCH_SCRIPT
    assert "PRODUCTION_JOB_DISABLED_AFTER_BATCH=YES" in WATCH_SCRIPT
    assert "FINAL_JOB_STATUS" in WATCH_SCRIPT
    disable_idx = WATCH_SCRIPT.index('"$CLI" jobs disable "$JOB_ID"')
    pause_idx = WATCH_SCRIPT.index('"$CLI" jobs pause "$JOB_ID"')
    assert disable_idx < pause_idx


def test_watch_script_treats_continuing_as_non_terminal_poll_state():
    assert "'continuing'" in WATCH_SCRIPT or "continuing" in WATCH_SCRIPT
    # the poll loop's terminal-state case must NOT include 'continuing' --
    # it's a healthy in-progress state, not a stopping point.
    case_block = WATCH_SCRIPT[WATCH_SCRIPT.index('case "$JOB_STATUS" in'):WATCH_SCRIPT.index("esac")]
    assert "continuing" not in case_block


def test_no_destructive_sql_anywhere_in_phase1_scripts():
    for path in SCRIPTS_DIR.glob("*phase1*"):
        text = path.read_text(encoding="utf-8")
        match = DESTRUCTIVE_SQL_RE.search(text)
        assert not match, f"destructive SQL pattern found in {path.name}: {match.group(0) if match else ''}"


def test_no_destructive_sql_in_run_goodsmile_scripts():
    for path in SCRIPTS_DIR.glob("run_goodsmile_*"):
        text = path.read_text(encoding="utf-8")
        match = DESTRUCTIVE_SQL_RE.search(text)
        assert not match, f"destructive SQL pattern found in {path.name}: {match.group(0) if match else ''}"
