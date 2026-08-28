#!/usr/bin/env bash
# DB Collector OS - Phase 1 batch #1 for the first production DB
# (job_prod_figure_official_site / 美少女フィギュア公式メーカーDB, Good Smile
# Company source: https://www.goodsmile.com/en/scalefigure_list).
#
# Paste this whole file into your VPS SSH session, or run it as
# `./scripts/run_goodsmile_phase1_batch1.sh` from /root/tools/db_collector_os.
# Either way is safe: everything runs inside one function, and nothing in
# this script ever calls `exit`, `logout`, `reboot`, `shutdown`, or
# otherwise touches your shell session.
#
# SSH-disconnect-safe design:
#   - Preflight checks + enabling the job run in your current shell (fast,
#     always finishes before you'd realistically disconnect mid-command).
#   - The actual crawl runs through the already-persistent
#     db-collector-worker@1.service -- it is completely unaffected by your
#     SSH session either way, with or without systemd-run.
#   - The part that WOULD otherwise die with your SSH session -- waiting for
#     the batch to settle, writing the full report, and disabling the job
#     afterward -- runs via a single, fixed-name `systemd-run` transient
#     unit (db-collector-phase1-batch1-goodsmile), so it keeps going even if
#     you disconnect. Re-running this script reuses/replaces that same named
#     unit rather than accumulating new ones (see the note on inotify watch
#     descriptor exhaustion from creating many transient units).
#
# This script never touches swap, resource_controller thresholds, or any
# other host-level resource configuration -- it only ever *reads* current
# resource state via the existing ResourceController gate, exactly like the
# Scheduler does for every other job.
#
# Safe to re-run any time.

db_collector_phase1_batch1_goodsmile() {
    local APP_DIR="${DB_COLLECTOR_APP_DIR:-/root/tools/db_collector_os}"
    local JOB_ID="job_prod_figure_official_site"
    local JOB_YAML="config/jobs/prod_figure_official_site.yaml"
    local LIST_URL="https://www.goodsmile.com/en/scalefigure_list"
    local PRODUCT_URL="https://www.goodsmile.com/en/product/1141716/Rikka%2BTakarada%2BAkane%2BShinjo%2Bfeat.%2Btoridamono"
    local WATCH_UNIT="db-collector-phase1-batch1-goodsmile"
    local ADMIN_PORT="${DB_COLLECTOR_ADMIN_PORT:-8787}"
    local SAMPLE_JOB_IDS="job_sample_official_site job_sample_local_business job_sample_person job_sample_api"
    local SKIP_START=0

    echo "===================================================================="
    echo " DB Collector OS -- Phase 1 batch #1 (Good Smile / $JOB_ID)"
    echo "===================================================================="

    cd "$APP_DIR" 2>/dev/null || {
        echo "[FATAL] app directory not found: $APP_DIR"
        return 1 2>/dev/null || true
    }

    local CLI="$APP_DIR/.venv/bin/db-collector"
    local PY="$APP_DIR/.venv/bin/python"
    [ -x "$CLI" ] || { echo "[FATAL] $CLI not found -- run scripts/install_vps.sh first"; return 1 2>/dev/null || true; }

    # -- git: clean working tree ----------------------------------------------
    echo; echo "--- preflight: git (clean working tree) ---"
    local DIRTY
    DIRTY="$(git status --short 2>/dev/null)"
    if [ -n "$DIRTY" ]; then
        echo "[BLOCK] working tree is not clean:"
        echo "$DIRTY"
        echo "        Commit/stash/discard local changes before running a batch."
        SKIP_START=1
    else
        echo "OK: working tree clean"
    fi

    # -- git: fetch + ff-only + HEAD vs origin --------------------------------
    echo; echo "--- preflight: git fetch --prune / ff-only merge / HEAD vs origin ---"
    local BRANCH; BRANCH="$(git branch --show-current 2>/dev/null || true)"
    if git fetch origin --prune "$BRANCH" 2>&1; then
        local LOCAL_HEAD REMOTE_HEAD
        LOCAL_HEAD="$(git rev-parse HEAD 2>/dev/null)"
        REMOTE_HEAD="$(git rev-parse "origin/$BRANCH" 2>/dev/null)"
        if [ "$LOCAL_HEAD" = "$REMOTE_HEAD" ]; then
            echo "OK: HEAD matches origin/$BRANCH ($LOCAL_HEAD)"
        elif git merge-base --is-ancestor "$LOCAL_HEAD" "$REMOTE_HEAD" 2>/dev/null; then
            # Local HEAD is behind origin but on the same line of history --
            # a fast-forward merge is safe and loses nothing. Only ever
            # advances local HEAD to match origin; never rewrites/rebases.
            echo "local HEAD ($LOCAL_HEAD) is behind origin/$BRANCH ($REMOTE_HEAD) -- fast-forwarding..."
            if git merge --ff-only "origin/$BRANCH" 2>&1; then
                LOCAL_HEAD="$(git rev-parse HEAD 2>/dev/null)"
                echo "OK: fast-forwarded to origin/$BRANCH ($LOCAL_HEAD)"
            else
                echo "[BLOCK] git merge --ff-only origin/$BRANCH failed unexpectedly."
                SKIP_START=1
            fi
        else
            echo "[BLOCK] HEAD ($LOCAL_HEAD) has diverged from origin/$BRANCH ($REMOTE_HEAD) --"
            echo "        not a fast-forward. Resolve manually (this script never rebases/force-merges),"
            echo "        then re-run this script."
            SKIP_START=1
        fi
    else
        echo "[WARN] git fetch failed (network?) -- could not verify drift; proceeding with caution"
    fi

    # -- DB backup --------------------------------------------------------------
    echo; echo "--- preflight: DB backup ---"
    ./scripts/backup.sh || { echo "[BLOCK] backup failed"; SKIP_START=1; }

    # -- DB integrity -----------------------------------------------------------
    echo; echo "--- preflight: DB integrity ---"
    "$CLI" integrity || { echo "[BLOCK] integrity check failed"; SKIP_START=1; }

    # -- compile check ------------------------------------------------------------
    echo; echo "--- preflight: compile check ---"
    if "$PY" -m compileall -q db_collector_os scripts; then
        echo "OK: db_collector_os/ and scripts/ compile cleanly"
    else
        echo "[BLOCK] compileall found a syntax error -- do not proceed"
        SKIP_START=1
    fi

    # -- worker reload gate: prevent the worker from serving a stale in-memory --
    # -- adapter registry after `git pull`/`git merge --ff-only` above landed --
    # -- new/changed adapter code (this is what caused "Unknown adapter: -------
    # -- figure_official_site" on a previous batch attempt -- a long-running --
    # -- worker process keeps its Python modules imported from whenever it ----
    # -- last started, regardless of what's now on disk). Restarts ONLY the ---
    # -- worker (never scheduler/admin), and only when it's safe to: the -------
    # -- production job is still disabled at this point in the script (it's ---
    # -- enabled further below, never before this), and no job anywhere is -----
    # -- currently mid-execution, so no other job's in-flight run is disturbed.
    echo; echo "--- preflight: worker reload (adapter code freshness) ---"
    if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
        local PROD_JOB_ENABLED
        PROD_JOB_ENABLED="$("$PY" -c "
from db_collector_os.config import load_config
from db_collector_os.database import Database
from db_collector_os.job_registry import JobRegistry
cfg = load_config('config/default.yaml')
db = Database(cfg.db_path)
job = JobRegistry(db).get('$JOB_ID')
print(bool(job and job.get('enabled')))
" 2>/dev/null)"
        local ANY_ACTIVE_RUN
        ANY_ACTIVE_RUN="$("$PY" -c "
from db_collector_os.config import load_config
from db_collector_os.database import Database
cfg = load_config('config/default.yaml')
db = Database(cfg.db_path)
rows = db.query(\"SELECT job_id FROM jobs WHERE status='running'\")
print(','.join(r['job_id'] for r in rows))
" 2>/dev/null)"
        if [ "$PROD_JOB_ENABLED" = "True" ]; then
            echo "[BLOCK] $JOB_ID is already enabled -- refusing to restart the worker mid-job. Investigate manually."
            SKIP_START=1
        elif [ -n "$ANY_ACTIVE_RUN" ]; then
            echo "[WARN] job(s) currently running ($ANY_ACTIVE_RUN) -- not restarting the worker so their"
            echo "       in-flight execution isn't disturbed. If figure_official_site adapter import fails"
            echo "       below, re-run this script once those jobs are idle."
        else
            echo "OK: $JOB_ID disabled, no job currently running -- safe to restart the worker"
            systemctl restart db-collector-worker@1.service 2>&1
            sleep 2
            if systemctl is-active --quiet db-collector-worker@1.service; then
                echo "OK: db-collector-worker@1.service active after restart"
            else
                echo "[BLOCK] db-collector-worker@1.service failed to become active after restart"
                SKIP_START=1
            fi
        fi
    else
        echo "[WARN] systemd not available here -- cannot restart/verify the worker"
    fi

    echo "--- adapter import smoke test (figure_official_site) ---"
    if "$PY" -c "
from db_collector_os.adapters import get_adapter
adapter = get_adapter('figure_official_site')
print('FIGURE_ADAPTER_IMPORT=PASS')
" 2>&1; then
        :
    else
        echo "[BLOCK] figure_official_site adapter failed to import -- do not proceed"
        SKIP_START=1
    fi

    # -- services active ----------------------------------------------------------
    echo; echo "--- preflight: services active ---"
    if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
        for svc in db-collector-scheduler.service db-collector-worker@1.service db-collector-admin.service; do
            if systemctl is-active --quiet "$svc"; then
                echo "OK: $svc active"
            else
                echo "[BLOCK] $svc is not active ($(systemctl is-active "$svc" 2>&1))"
                SKIP_START=1
            fi
        done
    else
        echo "[WARN] systemd not available in this shell context -- cannot verify services are active"
    fi

    # -- Admin HTTP 200 -----------------------------------------------------------
    echo; echo "--- preflight: Admin UI HTTP 200 ---"
    if command -v curl >/dev/null 2>&1; then
        local ADMIN_CODE
        ADMIN_CODE="$(curl -s -o /dev/null -m 5 -w '%{http_code}' "http://127.0.0.1:${ADMIN_PORT}/" 2>/dev/null)"
        if [ "$ADMIN_CODE" = "200" ]; then
            echo "OK: Admin UI http://127.0.0.1:${ADMIN_PORT}/ -> 200"
        else
            echo "[BLOCK] Admin UI http://127.0.0.1:${ADMIN_PORT}/ -> ${ADMIN_CODE:-no response}"
            SKIP_START=1
        fi
    else
        echo "[WARN] curl not available -- cannot verify Admin UI"
    fi

    # -- resource gate (reads the existing Resource Controller only -- never ---
    # -- modifies swap, thresholds, or any host resource configuration) --------
    echo; echo "--- preflight: resource gate ---"
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
        echo "OK: resource controller allows new job admission right now (RESOURCE_GATE=PASS)"
    else
        echo "[BLOCK] resource controller currently says NO to new job admission (RESOURCE_GATE=FAIL)."
        echo "        Not starting Phase 1 batch #1 now; already-running jobs are left alone."
        echo "        This script does not touch swap or Resource Controller thresholds --"
        echo "        re-run once load has come down on its own; it is safe to re-run."
        SKIP_START=1
    fi

    # -- robots.txt re-check (real HTTP access exists here, unlike in the ---
    # -- environment that authored this job) -----------------------------------
    echo; echo "--- preflight: robots.txt ---"
    if command -v curl >/dev/null 2>&1; then
        local ROBOTS_TXT
        ROBOTS_TXT="$(curl -sS -m 10 https://www.goodsmile.com/robots.txt 2>&1)"
        echo "$ROBOTS_TXT"
        if "$PY" -c "
from db_collector_os.fetching.robots import RobotsCache
rc = RobotsCache(user_agent='DBCollectorOS/0.1 (+https://github.com/hiro498/db_collector_os)')
list_ok = rc.can_fetch('$LIST_URL')
product_ok = rc.can_fetch('$PRODUCT_URL')
print('list URL allowed:', list_ok)
print('product URL allowed:', product_ok)
raise SystemExit(0 if (list_ok and product_ok) else 1)
"; then
            echo "OK: robots.txt allows both configured seed URLs"
        else
            echo "[BLOCK] robots.txt currently disallows one of the configured seed URLs -- do not proceed."
            SKIP_START=1
        fi
    else
        echo "[WARN] curl not available -- cannot re-verify robots.txt from here"
    fi
    echo "(this job's discovery.product_url_pattern structurally cannot match /search,"
    echo " and internal_links only follows links already found on fetched"
    echo " www.goodsmile.com pages -- see docs/first_production_db.md \"Phase 1 discovery method\")"

    # -- sample jobs disabled -------------------------------------------------
    echo; echo "--- preflight: sample jobs disabled ---"
    local ENABLED_SAMPLES
    ENABLED_SAMPLES="$("$PY" -c "
from db_collector_os.config import load_config
from db_collector_os.database import Database
from db_collector_os.job_registry import JobRegistry
cfg = load_config('config/default.yaml')
db = Database(cfg.db_path)
jr = JobRegistry(db)
bad = [j['job_id'] for j in jr.list() if j['job_id'].startswith('job_sample_') and j['enabled']]
print(','.join(bad))
" 2>/dev/null)"
    if [ -n "$ENABLED_SAMPLES" ]; then
        echo "[BLOCK] sample job(s) unexpectedly enabled: $ENABLED_SAMPLES"
        echo "        Fix with: $CLI jobs disable <job_id>"
        SKIP_START=1
    else
        echo "OK: all sample jobs ($SAMPLE_JOB_IDS) remain disabled"
    fi

    # -- register + enable -------------------------------------------------------
    echo; echo "--- register + enable job ---"
    if [ "$SKIP_START" = "1" ]; then
        echo "SKIPPED -- see [BLOCK] messages above. Fix them, then re-run this script."
        echo "GOODSMILE_PHASE1_BATCH1=FAIL"
        echo "PRODUCTION_CRAWL_STARTED=NO"
        return 0 2>/dev/null || true
    fi

    # -- capture the run_id landscape BEFORE this batch, so the watcher can ----
    # -- prove afterward that a genuinely NEW run_history row was created ------
    # -- (run_history is immutable execution history -- reusing/re-finalizing --
    # -- an old row is a bug, not a valid retry outcome). ------------------------
    local PREVIOUS_LATEST_RUN_ID
    PREVIOUS_LATEST_RUN_ID="$("$PY" -c "
from db_collector_os.config import load_config
from db_collector_os.database import Database
cfg = load_config('config/default.yaml')
db = Database(cfg.db_path)
row = db.query_one('SELECT run_id FROM run_history WHERE job_id=? ORDER BY started_at DESC, rowid DESC LIMIT 1', ('$JOB_ID',))
print(row['run_id'] if row else 'none')
" 2>/dev/null)"
    PREVIOUS_LATEST_RUN_ID="${PREVIOUS_LATEST_RUN_ID:-none}"
    echo "PREVIOUS_LATEST_RUN_ID=$PREVIOUS_LATEST_RUN_ID"

    "$CLI" jobs sync || { echo "[FATAL] jobs sync failed"; return 1 2>/dev/null || true; }

    # Guarantee this run's config seed_urls (both, after this revision's
    # config expansion) reach fetch_queue synchronously, from THIS process --
    # not by depending on db-collector-worker@1.service having reloaded code
    # that would otherwise enqueue them on its next run_once() tick. This
    # process always runs whatever is on disk right now (ff-only merge above
    # already brought it up to date), so it can't ever be stale the way a
    # long-running worker process can. Idempotent: never duplicates or
    # force-refetches an already-tracked URL.
    RESEED_OUTPUT="$("$CLI" jobs reseed "$JOB_ID" 2>&1)" || { echo "[FATAL] jobs reseed failed"; echo "$RESEED_OUTPUT"; return 1 2>/dev/null || true; }
    echo "$RESEED_OUTPUT"

    # jobs sync resets `enabled` to the YAML's value (false) -- enable it for
    # real now, against the running registry.
    "$CLI" jobs enable "$JOB_ID" || { echo "[FATAL] jobs enable failed"; return 1 2>/dev/null || true; }
    "$CLI" jobs resume "$JOB_ID" || { echo "[FATAL] jobs resume failed"; return 1 2>/dev/null || true; }
    echo "enabled + resumed $JOB_ID -- db-collector-worker@1.service will pick it up on its next tick"
    "$CLI" jobs show "$JOB_ID" || true

    # -- launch the SSH-disconnect-safe watcher (long-running: wait, report, ---
    # -- auto-disable) via a single named systemd-run transient unit -----------
    echo; echo "--- launching batch watcher (systemd-run) ---"
    if ! command -v systemd-run >/dev/null 2>&1 || [ ! -d /run/systemd/system ]; then
        echo "[WARN] systemd-run not available here -- the job is enabled and the persistent"
        echo "       worker will still run it, but no background watcher/report will run."
        echo "       Check progress manually with: $CLI jobs show $JOB_ID"
        echo "PRODUCTION_CRAWL_STARTED=PENDING"
        return 0 2>/dev/null || true
    fi

    if systemctl is-active --quiet "$WATCH_UNIT.service" 2>/dev/null; then
        echo "A watcher (unit $WATCH_UNIT) is already running from a previous invocation -- not starting a second one."
        echo "Follow it with: journalctl -u $WATCH_UNIT -f"
    else
        chmod +x scripts/_phase1_batch1_watch_and_report.sh scripts/_phase1_batch1_report.py 2>/dev/null || true
        systemd-run --unit="$WATCH_UNIT" \
            --description="DB Collector OS Phase 1 batch #1 watcher (Good Smile)" \
            --collect \
            --setenv=DB_COLLECTOR_APP_DIR="$APP_DIR" \
            --setenv=PHASE1_PREVIOUS_LATEST_RUN_ID="$PREVIOUS_LATEST_RUN_ID" \
            --setenv=PHASE1_LIST_URL="$LIST_URL" \
            bash "$APP_DIR/scripts/_phase1_batch1_watch_and_report.sh" \
            && echo "OK: watcher started as systemd unit '$WATCH_UNIT'" \
            || echo "[WARN] systemd-run failed to start the watcher -- job is still enabled and will still run via the worker"
    fi

    echo
    echo "Monitor with:"
    echo "  journalctl -u $WATCH_UNIT -f          # live watcher output"
    echo "  $CLI jobs show $JOB_ID"
    echo "  $CLI queue $JOB_ID"
    echo "  $CLI review"
    echo "  ls -t var/reports/ | head -1           # most recent full report file, once the watcher finishes"
    echo
    echo "PRODUCTION_CRAWL_STARTED=PENDING"
    echo "(the watcher disables the job automatically once the batch settles -- success or"
    echo " anomaly alike -- see var/reports/ for the full audit: entity/evidence counts,"
    echo " run_history, fetch_queue status + HTTP breakdown, checkpoint, DB integrity)"

    echo; echo "===================================================================="
    echo " done. This shell session is unaffected."
    echo "===================================================================="
    return 0 2>/dev/null || true
}

db_collector_phase1_batch1_goodsmile
