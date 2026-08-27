#!/usr/bin/env bash
# DB Collector OS - Phase 1 batch #1 for the first production DB
# (job_prod_figure_official_site / 美少女フィギュア公式メーカーDB, Good Smile
# Company source).
#
# Paste this whole file into your VPS SSH session, or run it as
# `./scripts/phase1_batch1_goodsmile.sh` from /root/tools/db_collector_os.
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
# Safe to re-run any time.

db_collector_phase1_batch1_goodsmile() {
    local APP_DIR="${DB_COLLECTOR_APP_DIR:-/root/tools/db_collector_os}"
    local JOB_ID="job_prod_figure_official_site"
    local JOB_YAML="config/jobs/prod_figure_official_site.yaml"
    local SEED_URL="https://www.goodsmile.com/en/product/1141716/Rikka%2BTakarada%2BAkane%2BShinjo%2Bfeat.%2Btoridamono"
    local WATCH_UNIT="db-collector-phase1-batch1-goodsmile"
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

    # -- git status (clean working tree) ------------------------------------
    echo; echo "--- preflight: git status ---"
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

    # -- HEAD / origin drift check -------------------------------------------
    echo; echo "--- preflight: HEAD vs origin ---"
    local BRANCH; BRANCH="$(git branch --show-current 2>/dev/null || true)"
    if git fetch origin "$BRANCH" 2>&1; then
        local LOCAL_HEAD REMOTE_HEAD
        LOCAL_HEAD="$(git rev-parse HEAD 2>/dev/null)"
        REMOTE_HEAD="$(git rev-parse "origin/$BRANCH" 2>/dev/null)"
        if [ "$LOCAL_HEAD" = "$REMOTE_HEAD" ]; then
            echo "OK: HEAD matches origin/$BRANCH ($LOCAL_HEAD)"
        else
            echo "[BLOCK] HEAD ($LOCAL_HEAD) does not match origin/$BRANCH ($REMOTE_HEAD)."
            echo "        Run scripts/update_vps.sh first, then re-run this script."
            SKIP_START=1
        fi
    else
        echo "[WARN] git fetch failed (network?) -- could not verify drift; proceeding with caution"
    fi

    # -- DB integrity ---------------------------------------------------------
    echo; echo "--- preflight: DB integrity ---"
    "$CLI" integrity || { echo "[BLOCK] integrity check failed"; SKIP_START=1; }

    # -- services active --------------------------------------------------------
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

    # -- resource gate (the existing Resource Controller -- the SAME gate ---
    # -- the Scheduler itself uses) --------------------------------------------
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
        echo "OK: resource controller allows new job admission right now"
    else
        echo "[BLOCK] resource controller currently says NO to new job admission."
        echo "        Not starting Phase 1 batch #1 now; already-running jobs are left alone."
        echo "        Re-run this script once load has come down -- it is safe to re-run."
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
seed_ok = rc.can_fetch('$SEED_URL')
root_ok = rc.can_fetch('https://www.goodsmile.com/')
print('seed URL allowed:', seed_ok)
print('site root allowed:', root_ok)
raise SystemExit(0 if seed_ok else 1)
"; then
            echo "OK: robots.txt allows the configured seed URL"
        else
            echo "[BLOCK] robots.txt currently disallows the configured seed URL -- do not proceed."
            SKIP_START=1
        fi
    else
        echo "[WARN] curl not available -- cannot re-verify robots.txt from here"
    fi
    echo "(this job never uses search-based discovery, and internal_links only follows"
    echo " links already found on fetched www.goodsmile.com pages -- see"
    echo " docs/first_production_db.md \"Phase 1 discovery method\")"

    # -- backup -----------------------------------------------------------------
    echo; echo "--- preflight: backup ---"
    ./scripts/backup.sh || { echo "[BLOCK] backup failed"; SKIP_START=1; }

    # -- register + enable -------------------------------------------------------
    echo; echo "--- register + enable job ---"
    if [ "$SKIP_START" = "1" ]; then
        echo "SKIPPED -- see [BLOCK] messages above. Fix them, then re-run this script."
        echo "PRODUCTION_CRAWL_STARTED=NO"
        return 0 2>/dev/null || true
    fi

    "$CLI" jobs sync || { echo "[FATAL] jobs sync failed"; return 1 2>/dev/null || true; }
    # jobs sync resets `enabled` to the YAML's value (false) -- enable it for
    # real now, against the running registry, same as activate_first_production_db.sh.
    "$CLI" jobs enable "$JOB_ID" || { echo "[FATAL] jobs enable failed"; return 1 2>/dev/null || true; }
    "$CLI" jobs resume "$JOB_ID" || { echo "[FATAL] jobs resume failed"; return 1 2>/dev/null || true; }
    echo "enabled + resumed $JOB_ID -- db-collector-worker@1.service will pick it up on its next tick"
    "$CLI" jobs show "$JOB_ID" || true

    # -- launch the SSH-disconnect-safe watcher ------------------------------
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
    echo " anomaly alike -- so it will not silently keep re-running; re-enable for the next batch)"

    echo; echo "===================================================================="
    echo " done. This shell session is unaffected."
    echo "===================================================================="
    return 0 2>/dev/null || true
}

db_collector_phase1_batch1_goodsmile
