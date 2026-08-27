#!/usr/bin/env bash
# DB Collector OS - one-shot VPS activation for the FIRST PRODUCTION DB
# (job_prod_figure_official_site / 美少女フィギュア公式メーカーDB).
#
# Paste this whole file into your VPS SSH session, or run it as
# `./scripts/activate_first_production_db.sh` from /root/tools/db_collector_os.
# Either way is safe: everything below runs inside one function, and nothing
# in this script ever calls `exit`, `logout`, `exec ssh`, or otherwise
# touches your shell session -- a failed step is reported and the function
# returns, but your SSH connection is left exactly as it was.
#
# This script does NOT restart scheduler/worker/admin (systemd already keeps
# them running, and restarting could hit an in-progress job's stop timeout).
# If it pulled new commits, it tells you to run scripts/update_vps.sh (or
# restart the systemd units yourself) before the new job will actually run
# with current code -- it does not do that automatically, to avoid ever
# touching an already-running job.
#
# Safe to re-run any time; every step here is idempotent.

db_collector_activate_first_production_db() {
    local APP_DIR="${DB_COLLECTOR_APP_DIR:-/root/tools/db_collector_os}"
    local JOB_ID="job_prod_figure_official_site"
    local JOB_YAML="config/jobs/prod_figure_official_site.yaml"
    local SKIP_ENABLE=0

    echo "===================================================================="
    echo " DB Collector OS -- activate first production DB"
    echo " job_id=$JOB_ID"
    echo "===================================================================="

    cd "$APP_DIR" 2>/dev/null || {
        echo "[FATAL] app directory not found: $APP_DIR"
        echo "        set DB_COLLECTOR_APP_DIR=/path/to/db_collector_os and re-run if it's elsewhere."
        return 1 2>/dev/null || true
    }

    local CLI="$APP_DIR/.venv/bin/db-collector"
    local PY="$APP_DIR/.venv/bin/python"
    [ -x "$CLI" ] || { echo "[FATAL] $CLI not found -- run scripts/install_vps.sh first"; return 1 2>/dev/null || true; }

    # -- [1/19] git status --------------------------------------------------
    echo; echo "--- [1/19] git status ---"
    git status --short || true
    local BRANCH; BRANCH="$(git branch --show-current)"
    echo "branch: $BRANCH"

    # -- [2/19] + [3/19] drift check + git pull --ff-only --------------------
    echo; echo "--- [2/19][3/19] drift check + git pull --ff-only ---"
    local HEAD_BEFORE; HEAD_BEFORE="$(git rev-parse HEAD)"
    if ! git diff --quiet || ! git diff --cached --quiet; then
        echo "[WARN] uncommitted local changes present -- NOT pulling. Resolve manually, then re-run."
    else
        if git fetch origin "$BRANCH" 2>&1; then
            if git merge --ff-only "origin/$BRANCH" 2>&1; then
                echo "OK: fast-forwarded (or already up to date)"
            else
                echo "[WARN] not fast-forwardable (local and origin/$BRANCH have diverged)."
                echo "       NOT overwriting anything -- resolve manually (see README Rollback/Update)."
            fi
        else
            echo "[WARN] git fetch failed (network?) -- continuing with the code already on disk."
        fi
    fi

    # -- [4/19] HEAD ----------------------------------------------------------
    echo; echo "--- [4/19] HEAD ---"
    local HEAD_AFTER; HEAD_AFTER="$(git rev-parse HEAD)"
    git log -1 --oneline || true
    local CODE_CHANGED=0
    if [ "$HEAD_BEFORE" != "$HEAD_AFTER" ]; then
        CODE_CHANGED=1
        echo "[NOTE] HEAD moved $HEAD_BEFORE -> $HEAD_AFTER."
        echo "       Already-running scheduler/worker/admin processes will NOT see this new code"
        echo "       until they restart. This script deliberately does not restart them (it never"
        echo "       touches an in-progress job). Once nothing else is mid-run, apply it with:"
        echo "         ./scripts/update_vps.sh          # or: systemctl restart db-collector-scheduler db-collector-worker@1 db-collector-admin"
    fi

    # -- [5/19] DB backup -------------------------------------------------------
    echo; echo "--- [5/19] DB backup ---"
    ./scripts/backup.sh || echo "[WARN] backup.sh reported an issue -- check output above before proceeding"

    # -- [6/19] integrity ----------------------------------------------------
    echo; echo "--- [6/19] integrity (pre-check) ---"
    "$CLI" integrity || echo "[WARN] integrity check failed"

    # -- [7/19] compile / smoke test ------------------------------------------
    echo; echo "--- [7/19] compile check ---"
    if "$PY" -m py_compile $(find db_collector_os -name '*.py'); then
        echo "compile OK"
    else
        echo "[FATAL] compile check failed -- do not proceed"
        return 1 2>/dev/null || true
    fi
    echo "--- [7/19] smoke test (offline, production-safe) ---"
    ./scripts/smoke_test.sh || echo "[WARN] smoke_test.sh reported issues -- review before enabling"

    # -- [8/19] production job config -----------------------------------------
    echo; echo "--- [8/19] production job config ---"
    if [ ! -f "$JOB_YAML" ]; then
        echo "[FATAL] $JOB_YAML not found"
        return 1 2>/dev/null || true
    fi
    cat "$JOB_YAML" || true
    if grep -q "REPLACE_ME" "$JOB_YAML"; then
        echo "[BLOCK] $JOB_YAML still has REPLACE_ME placeholder URLs."
        echo "        Edit it with a real, robots-permitting official site before enabling."
        SKIP_ENABLE=1
    else
        echo "OK: no REPLACE_ME placeholders remain"
    fi

    # -- [9/19] adapter check --------------------------------------------------
    echo; echo "--- [9/19] adapter check ---"
    if "$PY" -c "
from db_collector_os.adapters import get_adapter
a = get_adapter('figure_official_site')
print('adapter OK:', a.name, a.entity_type, a.required_fields)
"; then
        :
    else
        echo "[FATAL] adapter failed to load"
        return 1 2>/dev/null || true
    fi

    # -- [10/19] + resource gate (used again after sync for the real check) --
    echo; echo "--- [10/19] sample jobs currently registered (pre-sync) ---"
    "$CLI" jobs list 2>/dev/null | grep sample || echo "(none registered yet)"

    # -- [11/19] resource check (CPU/RAM/swap/disk/load via the existing --
    # -- Resource Controller -- the SAME gate the Scheduler itself uses) -----
    echo; echo "--- [11/19] resource check (existing Resource Controller) ---"
    local RESOURCE_OK=1
    if "$PY" -c "
from db_collector_os.config import load_config
from db_collector_os.resource_controller import ResourceController
cfg = load_config('config/default.yaml')
rc = ResourceController(cfg.resource_thresholds)
snap = rc.snapshot()
ok, reason = rc.can_admit_new_job()
print(f'cpu={snap.cpu_percent:.1f}% ram={snap.ram_percent:.1f}% swap={snap.swap_percent:.1f}% disk={snap.disk_percent:.1f}% load={snap.load_average:.2f}')
print('can_admit_new_job:', ok, '-', reason)
raise SystemExit(0 if ok else 1)
"; then
        echo "OK: resource controller allows new job admission right now"
    else
        echo "[BLOCK] resource controller currently says NO to new job admission."
        echo "        Not starting Phase 1 now (already-running jobs are left alone)."
        echo "        Re-run this script once load has come down -- it is safe to re-run."
        RESOURCE_OK=0
        SKIP_ENABLE=1
    fi

    # -- [12/19] register job (jobs sync) -------------------------------------
    echo; echo "--- [12/19] register production job (jobs sync) ---"
    "$CLI" jobs sync || echo "[WARN] jobs sync reported an issue -- check output above"

    # sample-job regression check happens AFTER sync, against the real registry
    echo "--- sample jobs regression check (post-sync, must all stay disabled) ---"
    local SAMPLE_ENABLED
    SAMPLE_ENABLED="$("$PY" -c "
from db_collector_os.config import load_config
from db_collector_os.database import Database
from db_collector_os.job_registry import JobRegistry
cfg = load_config('config/default.yaml')
db = Database(cfg.db_path)
jr = JobRegistry(db)
bad = [j['job_id'] for j in jr.list() if j['job_id'].startswith('job_sample_') and j['enabled']]
print(','.join(bad))
")"
    if [ -n "$SAMPLE_ENABLED" ]; then
        echo "[BLOCK] sample job(s) unexpectedly enabled: $SAMPLE_ENABLED"
        echo "        Not proceeding -- fix with: db-collector jobs disable <job_id>"
        SKIP_ENABLE=1
    else
        echo "OK: all sample_* jobs remain disabled"
    fi

    # -- [13/19] enable production job (enabled=true) -------------------------
    echo; echo "--- [13/19] enable production job ---"
    if [ "$SKIP_ENABLE" = "1" ]; then
        echo "SKIPPED -- see [BLOCK] messages above. Once fixed, re-run this script, or run:"
        echo "  $CLI jobs enable $JOB_ID && $CLI jobs resume $JOB_ID"
    else
        "$CLI" jobs enable "$JOB_ID" || echo "[WARN] jobs enable failed"
        "$CLI" jobs resume "$JOB_ID" || echo "[WARN] jobs resume failed"
        echo "enabled + resumed $JOB_ID"
    fi

    # -- [14/19] Phase 1 admission (small, safe upper bounds already in the ---
    # -- job YAML: max_pages=30, concurrency=1, rate_limit=3.0s) --------------
    echo; echo "--- [14/19] job state ---"
    "$CLI" jobs show "$JOB_ID" || true

    # -- [15/19] scheduler/worker active? --------------------------------------
    echo; echo "--- [15/19] scheduler/worker active ---"
    if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
        { systemctl is-active db-collector-scheduler.service 2>&1 || true; } | sed 's/^/scheduler: /'
        { systemctl is-active db-collector-worker@1.service 2>&1 || true; } | sed 's/^/worker@1:  /'
        { systemctl is-active db-collector-admin.service 2>&1 || true; } | sed 's/^/admin:     /'
    else
        echo "[SKIP] systemd not available in this shell context"
    fi

    # -- [16/19] queue / checkpoint --------------------------------------------
    echo; echo "--- [16/19] queue / checkpoint ---"
    "$CLI" queue "$JOB_ID" || true

    # -- [17/19] Admin HTTP 200 -------------------------------------------------
    echo; echo "--- [17/19] Admin UI reachability ---"
    if command -v curl >/dev/null 2>&1; then
        curl -s -o /dev/null -m 5 -w "admin HTTP %{http_code}\n" http://127.0.0.1:8787/ 2>&1 \
            || echo "[WARN] admin UI not reachable on 127.0.0.1:8787"
    else
        echo "[SKIP] curl not available"
    fi

    # -- [18/19] integrity (final) ------------------------------------------
    echo; echo "--- [18/19] integrity (final) ---"
    "$CLI" integrity || echo "[WARN] final integrity check failed"

    # -- [19/19] execution start confirmation ----------------------------------
    echo; echo "--- [19/19] summary ---"
    if [ "$SKIP_ENABLE" = "1" ]; then
        echo "PRODUCTION_CRAWL_STARTED=NO"
        [ "$RESOURCE_OK" = "0" ] && echo "REASON=resource_controller_denied_admission (safe to re-run later)"
        echo "See [BLOCK]/[FATAL] messages above for what to fix, then re-run this script."
    else
        echo "PRODUCTION_CRAWL_STARTED=PENDING"
        echo "Job is enabled; the already-running scheduler/worker will pick it up on their"
        echo "own next tick (resource-gated, same as every other job). Check progress with:"
        echo "  $CLI jobs show $JOB_ID"
        echo "  $CLI queue $JOB_ID"
        echo "  $CLI review"
        echo "  journalctl -u db-collector-worker@1 -f"
        [ "$CODE_CHANGED" = "1" ] && echo "  (remember: new code was pulled -- see the [4/19] NOTE above about restarting services)"
    fi

    echo; echo "===================================================================="
    echo " done. This shell session is unaffected."
    echo "===================================================================="
    return 0 2>/dev/null || true
}

db_collector_activate_first_production_db
