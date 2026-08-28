"""Static assertions over the VPS batch scripts' text: things that can't be
exercised by an actual VPS run in this environment (no systemd, no real
worker service) but must never regress -- SSH-session safety, the worker
reload gate that prevents serving a stale in-memory adapter registry after
`git pull`, and the run-lifecycle / seed-reporting additions.
"""

from __future__ import annotations

from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
MAIN_SCRIPT = (SCRIPTS_DIR / "run_goodsmile_phase1_batch1.sh").read_text(encoding="utf-8")
WATCH_SCRIPT = (SCRIPTS_DIR / "_phase1_batch1_watch_and_report.sh").read_text(encoding="utf-8")


def test_no_shell_terminating_commands_at_top_level():
    import re

    for script_name, text in (("main", MAIN_SCRIPT), ("watch", WATCH_SCRIPT)):
        # watch script legitimately uses `exit` inside its own systemd-run
        # process (documented in its header) -- only the main script (meant
        # to be pasted into an interactive SSH session) must never do so.
        if script_name == "main":
            for bad in (r"^\s*exit\b", r"^\s*logout\b", r"^\s*reboot\b", r"^\s*shutdown\b", r"exec\s+ssh"):
                assert not re.search(bad, text, re.MULTILINE), f"found forbidden `{bad}` in {script_name} script"


def test_main_script_never_disconnects_or_double_launches():
    assert "db_collector_phase1_batch1_goodsmile() {" in MAIN_SCRIPT
    assert MAIN_SCRIPT.rstrip().endswith("db_collector_phase1_batch1_goodsmile")
    assert "systemd-run" in MAIN_SCRIPT
    assert 'systemctl is-active --quiet "$WATCH_UNIT.service"' in MAIN_SCRIPT  # double-launch guard


def test_main_script_has_full_precheck_sequence():
    required_markers = [
        "git status --short",
        "git fetch origin --prune",
        "git merge --ff-only",
        "compileall",
        "backup.sh",
        '"$CLI" integrity',
        "services active",
        "Admin UI HTTP 200",
        "resource gate",
        "robots.txt",
        "sample jobs disabled",
    ]
    for marker in required_markers:
        assert marker in MAIN_SCRIPT, f"missing precheck marker: {marker!r}"


def test_main_script_has_worker_reload_gate():
    assert "worker reload" in MAIN_SCRIPT.lower()
    assert "systemctl restart db-collector-worker@1.service" in MAIN_SCRIPT
    assert "FIGURE_ADAPTER_IMPORT=PASS" in MAIN_SCRIPT
    # safety preconditions before restarting
    assert "PROD_JOB_ENABLED" in MAIN_SCRIPT
    assert "ANY_ACTIVE_RUN" in MAIN_SCRIPT
    # never restarts scheduler/admin from this script
    assert "systemctl restart db-collector-scheduler" not in MAIN_SCRIPT
    assert "systemctl restart db-collector-admin" not in MAIN_SCRIPT


def test_main_script_captures_previous_latest_run_id_and_passes_to_watcher():
    assert "PREVIOUS_LATEST_RUN_ID" in MAIN_SCRIPT
    assert "--setenv=PHASE1_PREVIOUS_LATEST_RUN_ID=" in MAIN_SCRIPT
    assert "--setenv=PHASE1_LIST_URL=" in MAIN_SCRIPT


def test_main_script_runs_jobs_reseed_after_sync_before_enable():
    # The config-seed guarantee (db-collector jobs reseed) must run
    # synchronously from this fresh script process -- independent of
    # whether db-collector-worker@1.service has reloaded code -- and must
    # run after `jobs sync` (so config_json is current) and before `jobs
    # enable`/`jobs resume` (so the queue is already populated before the
    # job starts being picked up).
    sync_idx = MAIN_SCRIPT.index('"$CLI" jobs sync')
    reseed_idx = MAIN_SCRIPT.index('"$CLI" jobs reseed "$JOB_ID"')
    enable_idx = MAIN_SCRIPT.index('"$CLI" jobs enable "$JOB_ID"')
    assert sync_idx < reseed_idx < enable_idx


def test_watch_script_has_run_lifecycle_gate():
    assert "RUN_LIFECYCLE_GATE" in WATCH_SCRIPT
    assert "PREVIOUS_LATEST_RUN_ID" in WATCH_SCRIPT
    assert "CURRENT_LATEST_RUN_ID" in WATCH_SCRIPT
    assert "run_id_reused" in WATCH_SCRIPT


def test_watch_script_reports_seed_list_and_disables_job_with_exact_key():
    assert "NEW_SEED_LIST_PRESENT_IN_QUEUE" in WATCH_SCRIPT
    assert "SCALE_LIST_FETCHED" in WATCH_SCRIPT
    assert "PRODUCTION_JOB_DISABLED_AFTER_BATCH=YES" in WATCH_SCRIPT


def test_watch_script_gates_on_elevated_http_error_counts():
    for code in ("403", "404", "429", "5XX"):
        assert f"HTTP_{code}_COUNT" in WATCH_SCRIPT
