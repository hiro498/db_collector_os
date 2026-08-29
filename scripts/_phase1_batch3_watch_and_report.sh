#!/usr/bin/env bash
# Internal helper for scripts/run_goodsmile_phase1_batch3.sh. Invoked via a
# named `systemd-run` transient unit so it (and its report) survives an SSH
# disconnect even though the actual crawl runs through the
# already-persistent db-collector-worker@1.service, not through this
# process. Polls until the job settles (or a generous timeout), writes a
# full report + evaluates the Phase 1 batch #3 PASS/PARTIAL/FAIL result,
# and always disables AND pauses the job afterward (success or anomaly),
# per the Phase 1 "one batch at a time" policy -- same design as batch #1/
# #2's watchers, reused rather than reinvented.
#
# batch #3 is specifically about proving the run-lifecycle fix: a
# successful run must never leave the job showing status=retry, and one
# logical batch must not fragment into dozens of one-page runs 15 seconds
# apart. See RUN_COUNT/LIFECYCLE_OK below.
#
# Not meant to be run directly by a human -- use
# scripts/run_goodsmile_phase1_batch3.sh, which launches this via systemd-run.
set -uo pipefail  # deliberately no -e: every step below must still run so a report is always produced

APP_DIR="${DB_COLLECTOR_APP_DIR:-/root/tools/db_collector_os}"
JOB_ID="job_prod_figure_official_site"
TIMEOUT_SECONDS="${PHASE1_WATCH_TIMEOUT_SECONDS:-1800}"
POLL_SECONDS="${PHASE1_WATCH_POLL_SECONDS:-15}"
ADMIN_PORT="${DB_COLLECTOR_ADMIN_PORT:-8787}"
PREVIOUS_LATEST_RUN_ID="${PHASE1_PREVIOUS_LATEST_RUN_ID:-none}"
LIST_URL="${PHASE1_LIST_URL:-https://www.goodsmile.com/en/scalefigure_list}"
ENTITY_COUNT_BEFORE="${PHASE1_ENTITY_COUNT_BEFORE:-0}"
RUN_COUNT_BEFORE="${PHASE1_RUN_COUNT_BEFORE:-0}"
QUEUE_PENDING_BEFORE="${PHASE1_QUEUE_PENDING_BEFORE:-0}"

cd "$APP_DIR" || { echo "[FATAL] app dir not found: $APP_DIR"; exit 1; }
# `exit` is fine in this file specifically: it only ever runs inside its own
# systemd-run process, never in an operator's interactive shell.

CLI="$APP_DIR/.venv/bin/db-collector"
PY="$APP_DIR/.venv/bin/python"

REPORT_DIR="$APP_DIR/var/reports"
mkdir -p "$REPORT_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
REPORT_FILE="$REPORT_DIR/phase1_batch3_${STAMP}.txt"

log() { echo "$*" | tee -a "$REPORT_FILE"; }

log "===================================================================="
log " Phase 1 batch #3 watcher started: $(date -u +%FT%TZ)"
log " job_id=$JOB_ID timeout=${TIMEOUT_SECONDS}s poll=${POLL_SECONDS}s"
log " entity_count_before=$ENTITY_COUNT_BEFORE run_count_before=$RUN_COUNT_BEFORE queue_pending_before=$QUEUE_PENDING_BEFORE"
log " report file: $REPORT_FILE"
log "===================================================================="

START_TS=$(date +%s)
FINAL_STATUS="timeout"

while true; do
    NOW_TS=$(date +%s)
    ELAPSED=$((NOW_TS - START_TS))
    if [ "$ELAPSED" -ge "$TIMEOUT_SECONDS" ]; then
        log "[WARN] timeout after ${ELAPSED}s waiting for the batch to settle"
        FINAL_STATUS="timeout"
        break
    fi

    JOB_STATUS="$("$CLI" jobs show "$JOB_ID" 2>/dev/null | "$PY" -c "import json,sys
try:
    print(json.load(sys.stdin).get('status', ''))
except Exception:
    print('')
" 2>/dev/null)"

    log "[poll] t=${ELAPSED}s job_status=${JOB_STATUS:-unknown}"

    # 'continuing' is a healthy in-progress state (see JobStatus.CONTINUING)
    # -- keep polling through it exactly like 'queued'/'running', only
    # 'completed'/'failed'/'paused' end the wait.
    case "$JOB_STATUS" in
        completed|failed|paused)
            FINAL_STATUS="$JOB_STATUS"
            break
            ;;
    esac

    sleep "$POLL_SECONDS"
done

log ""
log "--- final job state ---"
"$CLI" jobs show "$JOB_ID" 2>&1 | tee -a "$REPORT_FILE"

log ""
"$PY" scripts/_phase1_batch3_report.py "$JOB_ID" "$ENTITY_COUNT_BEFORE" "$RUN_COUNT_BEFORE" 2>&1 | tee -a "$REPORT_FILE"

log ""
log "--- DB integrity ---"
INTEGRITY_OUTPUT="$("$CLI" integrity 2>&1)"
echo "$INTEGRITY_OUTPUT" | tee -a "$REPORT_FILE"
log "DB_INTEGRITY=$INTEGRITY_OUTPUT"

log ""
log "--- services active (after batch) ---"
SERVICES_OK=1
if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
    for svc in db-collector-scheduler.service db-collector-worker@1.service db-collector-admin.service; do
        if systemctl is-active --quiet "$svc"; then
            log "OK: $svc active"
        else
            log "FAIL: $svc not active"
            SERVICES_OK=0
        fi
    done
else
    log "[WARN] systemd not available -- cannot verify services active"
fi

log ""
log "--- Admin HTTP ---"
ADMIN_CODE="$(curl -s -o /dev/null -m 5 -w '%{http_code}' "http://127.0.0.1:${ADMIN_PORT}/" 2>/dev/null)"
log "admin_http_status=${ADMIN_CODE:-no response}"

log ""
log "--- sample jobs disabled (post-batch) ---"
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
    log "FAIL: sample job(s) unexpectedly enabled: $ENABLED_SAMPLES"
else
    log "OK: sample jobs remain disabled"
fi

log ""
log "--- other production jobs unaffected ---"
OTHER_ENABLED_JOBS="$("$PY" -c "
from db_collector_os.config import load_config
from db_collector_os.database import Database
from db_collector_os.job_registry import JobRegistry
cfg = load_config('config/default.yaml')
db = Database(cfg.db_path)
jr = JobRegistry(db)
bad = [j['job_id'] for j in jr.list() if j['job_id'] != '$JOB_ID' and not j['job_id'].startswith('job_sample_') and j['enabled']]
print(','.join(bad))
" 2>/dev/null)"
if [ -n "$OTHER_ENABLED_JOBS" ]; then
    log "[WARN] other production job(s) enabled: $OTHER_ENABLED_JOBS (this script never touches them -- verify intentional)"
else
    log "OK: no other production job was enabled by this batch"
fi

log ""
log "--- seed URL queue state (Scale Figure list) ---"
SEED_QUEUE_STATE="$("$PY" -c "
from db_collector_os.config import load_config
from db_collector_os.database import Database
cfg = load_config('config/default.yaml')
db = Database(cfg.db_path)
row = db.query_one(\"SELECT status, last_http_status FROM fetch_queue WHERE job_id=? AND url=?\", ('$JOB_ID', '$LIST_URL'))
if not row:
    print('absent,none')
else:
    print(f\"{row['status']},{row['last_http_status']}\")
" 2>/dev/null)"
SEED_QUEUE_STATUS="${SEED_QUEUE_STATE%,*}"
SEED_QUEUE_HTTP="${SEED_QUEUE_STATE#*,}"
if [ "$SEED_QUEUE_STATUS" = "absent" ]; then
    log "NEW_SEED_LIST_PRESENT_IN_QUEUE=NO"
    log "SCALE_LIST_FETCHED=NO"
else
    log "NEW_SEED_LIST_PRESENT_IN_QUEUE=YES"
    if [ "$SEED_QUEUE_STATUS" = "done" ] && [ "$SEED_QUEUE_HTTP" = "200" ]; then
        log "SCALE_LIST_FETCHED=YES"
    else
        log "SCALE_LIST_FETCHED=NO (status=$SEED_QUEUE_STATUS http=$SEED_QUEUE_HTTP)"
    fi
fi

log ""
log "--- resource state after batch ---"
"$PY" -c "
from db_collector_os.config import load_config
from db_collector_os.resource_controller import ResourceController
cfg = load_config('config/default.yaml')
rc = ResourceController(cfg.resource_thresholds)
snap = rc.snapshot()
ok, reason = rc.can_admit_new_job()
print(f'RESOURCE_AFTER_cpu={snap.cpu_percent:.1f}%')
print(f'RESOURCE_AFTER_ram={snap.ram_percent:.1f}%')
print(f'RESOURCE_AFTER_swap={snap.swap_percent:.1f}%')
print(f'RESOURCE_AFTER_disk={snap.disk_percent:.1f}%')
print(f'RESOURCE_AFTER_load={snap.load_average:.2f}')
print('RESOURCE_AFTER_can_admit_new_job=' + str(ok) + ' - ' + reason)
" 2>&1 | tee -a "$REPORT_FILE"

# -- result gate ---------------------------------------------------------
LATEST_RUN_ID="$(grep -oE 'LATEST_RUN_ID=[A-Za-z0-9_]+' "$REPORT_FILE" | tail -1 | cut -d= -f2)"
LATEST_RUN_STATUS="$(grep -oE 'LATEST_RUN_STATUS=[a-z_]+' "$REPORT_FILE" | tail -1 | cut -d= -f2)"
BATCH_FETCHED="$(grep -oE 'BATCH_FETCHED=[0-9]+' "$REPORT_FILE" | tail -1 | cut -d= -f2)"
BATCH_INSERTED="$(grep -oE 'BATCH_INSERTED=[0-9]+' "$REPORT_FILE" | tail -1 | cut -d= -f2)"
BATCH_ERRORS="$(grep -oE 'BATCH_ERRORS=[0-9]+' "$REPORT_FILE" | tail -1 | cut -d= -f2)"
OPEN_REVIEW_COUNT="$(grep -oE 'OPEN_REVIEW_COUNT=[0-9]+' "$REPORT_FILE" | tail -1 | cut -d= -f2)"
ENTITY_COUNT="$(grep -oE 'ENTITY_COUNT=[0-9]+' "$REPORT_FILE" | tail -1 | cut -d= -f2)"
ENTITY_DELTA="$(grep -oE 'ENTITY_DELTA=-?[0-9]+' "$REPORT_FILE" | tail -1 | cut -d= -f2)"
RUN_COUNT="$(grep -oE 'RUN_COUNT=[0-9]+' "$REPORT_FILE" | tail -1 | cut -d= -f2)"
LIFECYCLE_OK="$(grep -oE 'LIFECYCLE_OK=[A-Z]+' "$REPORT_FILE" | tail -1 | cut -d= -f2)"
NON_COMPLETED_RUNS="$(grep -oE 'NON_COMPLETED_RUNS_THIS_BATCH=[0-9]+' "$REPORT_FILE" | tail -1 | cut -d= -f2)"
HTTP_403_COUNT="$(grep -oE 'HTTP_403_COUNT=[0-9]+' "$REPORT_FILE" | tail -1 | cut -d= -f2)"
HTTP_404_COUNT="$(grep -oE 'HTTP_404_COUNT=[0-9]+' "$REPORT_FILE" | tail -1 | cut -d= -f2)"
HTTP_429_COUNT="$(grep -oE 'HTTP_429_COUNT=[0-9]+' "$REPORT_FILE" | tail -1 | cut -d= -f2)"
HTTP_5XX_COUNT="$(grep -oE 'HTTP_5XX_COUNT=[0-9]+' "$REPORT_FILE" | tail -1 | cut -d= -f2)"
MAX_ERROR_RATE="$("$PY" -c "
from db_collector_os.config import load_config
from db_collector_os.database import Database
from db_collector_os.job_registry import JobRegistry
cfg = load_config('config/default.yaml')
db = Database(cfg.db_path)
job = JobRegistry(db).get('$JOB_ID')
print((job.get('config_json') or {}).get('phase1_conditions', {}).get('max_error_rate', 0.5) if job else 0.5)
" 2>/dev/null)"

log ""
log "===================================================================="
log " Phase 1 batch #3 -- result evaluation"
log "===================================================================="

log "PREVIOUS_LATEST_RUN_ID=$PREVIOUS_LATEST_RUN_ID"
log "CURRENT_LATEST_RUN_ID=${LATEST_RUN_ID:-none}"
if [ "$PREVIOUS_LATEST_RUN_ID" != "none" ] && [ "${LATEST_RUN_ID:-none}" = "$PREVIOUS_LATEST_RUN_ID" ]; then
    log "RUN_LIFECYCLE_GATE=FAIL"
else
    log "RUN_LIFECYCLE_GATE=PASS"
fi

# -- structural failures: something is actually broken -> FAIL, full stop.
FAIL_REASONS=""
if [ "$PREVIOUS_LATEST_RUN_ID" != "none" ] && [ "${LATEST_RUN_ID:-none}" = "$PREVIOUS_LATEST_RUN_ID" ]; then
    FAIL_REASONS="${FAIL_REASONS}run_id_reused(${LATEST_RUN_ID:-none});"
fi
[ "${LATEST_RUN_ID:-none}" != "none" ] || FAIL_REASONS="${FAIL_REASONS}no_run_history_row_created;"
INTEGRITY_OK=0
[ "$INTEGRITY_OUTPUT" = "ok" ] && INTEGRITY_OK=1
[ "$INTEGRITY_OK" = "1" ] || FAIL_REASONS="${FAIL_REASONS}db_integrity_not_ok;"
[ "$FINAL_STATUS" = "completed" ] || FAIL_REASONS="${FAIL_REASONS}job_status_not_completed(${FINAL_STATUS});"
[ "${LATEST_RUN_STATUS:-}" = "completed" ] || FAIL_REASONS="${FAIL_REASONS}latest_run_not_completed(${LATEST_RUN_STATUS:-none});"
[ "$SERVICES_OK" = "1" ] || FAIL_REASONS="${FAIL_REASONS}services_not_active;"
[ "$ADMIN_CODE" = "200" ] || FAIL_REASONS="${FAIL_REASONS}admin_http_not_200(${ADMIN_CODE:-none});"
[ -z "$ENABLED_SAMPLES" ] || FAIL_REASONS="${FAIL_REASONS}sample_jobs_enabled(${ENABLED_SAMPLES});"

# -- lifecycle correctness: the actual point of batch #3. A successful ----
# -- (error_total==0) batch must never leave the job showing status=retry, --
# -- and every run_history row this batch created must have finalized -----
# -- as 'completed' (an immutable row stuck at anything else means a run ---
# -- crashed mid-flight and was abandoned, not a healthy continuation).
[ "${LIFECYCLE_OK:-NO}" = "YES" ] || FAIL_REASONS="${FAIL_REASONS}lifecycle_not_ok(non_completed_runs=${NON_COMPLETED_RUNS:-unknown});"

# -- "no runaway 15-second run creation": if there was real pending work ---
# -- before this batch started, one run should process considerably more --
# -- than one page each -- otherwise the batch fragmented into a run per --
# -- page again, the exact bug this batch exists to catch.
if [ "${QUEUE_PENDING_BEFORE:-0}" -gt 1 ] 2>/dev/null && [ "${BATCH_FETCHED:-0}" -gt 5 ] 2>/dev/null && [ "${RUN_COUNT:-0}" -gt 0 ] 2>/dev/null; then
    AVG_FETCHED_PER_RUN_OK="$("$PY" -c "print(1 if (${BATCH_FETCHED:-0} / ${RUN_COUNT:-1}) >= 2 else 0)" 2>/dev/null)"
    if [ "${AVG_FETCHED_PER_RUN_OK:-0}" != "1" ]; then
        FAIL_REASONS="${FAIL_REASONS}runaway_one_page_per_run(fetched=${BATCH_FETCHED:-0} run_count=${RUN_COUNT:-0});"
    fi
fi

if [ "${BATCH_FETCHED:-0}" -gt 0 ] 2>/dev/null; then
    ERROR_RATE_OK="$("$PY" -c "print(1 if (${BATCH_ERRORS:-0} / ${BATCH_FETCHED:-1}) <= ${MAX_ERROR_RATE:-0.5} else 0)" 2>/dev/null)"
    [ "${ERROR_RATE_OK:-0}" = "1" ] || FAIL_REASONS="${FAIL_REASONS}error_rate_exceeds_max(${BATCH_ERRORS:-0}/${BATCH_FETCHED:-0} > ${MAX_ERROR_RATE:-0.5});"
fi

ENTITY_COUNT_VAL="${ENTITY_COUNT:-0}"
if [ "$ENTITY_COUNT_VAL" -gt 10 ] 2>/dev/null; then
    REVIEW_BOUND="$ENTITY_COUNT_VAL"
else
    REVIEW_BOUND=10
fi
[ "${OPEN_REVIEW_COUNT:-0}" -le "$REVIEW_BOUND" ] 2>/dev/null || FAIL_REASONS="${FAIL_REASONS}open_review_count_elevated(${OPEN_REVIEW_COUNT:-0} > ${REVIEW_BOUND});"

FETCHED_VAL="${BATCH_FETCHED:-0}"
HTTP_BOUND="$("$PY" -c "print(max(5, int(${FETCHED_VAL:-0} * 0.2)))" 2>/dev/null)"
HTTP_BOUND="${HTTP_BOUND:-5}"
[ "${HTTP_403_COUNT:-0}" -le "$HTTP_BOUND" ] 2>/dev/null || FAIL_REASONS="${FAIL_REASONS}http_403_elevated(${HTTP_403_COUNT:-0} > ${HTTP_BOUND});"
[ "${HTTP_404_COUNT:-0}" -le "$HTTP_BOUND" ] 2>/dev/null || FAIL_REASONS="${FAIL_REASONS}http_404_elevated(${HTTP_404_COUNT:-0} > ${HTTP_BOUND});"
[ "${HTTP_429_COUNT:-0}" -le "$HTTP_BOUND" ] 2>/dev/null || FAIL_REASONS="${FAIL_REASONS}http_429_elevated(${HTTP_429_COUNT:-0} > ${HTTP_BOUND});"
[ "${HTTP_5XX_COUNT:-0}" -eq 0 ] 2>/dev/null || FAIL_REASONS="${FAIL_REASONS}http_5xx_present(${HTTP_5XX_COUNT:-0});"

# -- PARTIAL: nothing broken, but this batch didn't grow the population. --
# -- ENTITY_DELTA<=0 is NOT required to be positive on its own (re-fetching
# -- already-known entities with an otherwise-empty queue is a legitimate,
# -- healthy outcome) -- only flagged as PARTIAL (informational), never FAIL.
PARTIAL_REASONS=""
[ "${ENTITY_DELTA:-0}" -gt 0 ] 2>/dev/null || PARTIAL_REASONS="${PARTIAL_REASONS}entity_delta_not_gt_0(${ENTITY_DELTA:-unknown}, may be legitimate if the queue was already exhausted);"

if [ -n "$FAIL_REASONS" ]; then
    log "PHASE1_RESULT=FAIL"
    log "FAIL_REASONS=$FAIL_REASONS"
    log "READY_FOR_BATCH4=NO"
elif [ -n "$PARTIAL_REASONS" ]; then
    log "PHASE1_RESULT=PARTIAL"
    log "PARTIAL_REASONS=$PARTIAL_REASONS"
    log "READY_FOR_BATCH4=YES"
else
    log "PHASE1_RESULT=PASS"
    log "READY_FOR_BATCH4=YES"
fi

log ""
log "Disabling AND pausing job as designed (one batch at a time -- success,"
log "partial, or anomaly alike -- see docs/first_production_db.md). Pausing"
log "in addition to disabling guarantees the job's final displayed status is"
log "never left as 'continuing'/'retry' -- both could otherwise look like"
log "unfinished or failed work still pending, when the batch has in fact"
log "ended and the job is deliberately stopped."
"$CLI" jobs disable "$JOB_ID" 2>&1 | tee -a "$REPORT_FILE"
"$CLI" jobs pause "$JOB_ID" 2>&1 | tee -a "$REPORT_FILE"
log "PRODUCTION_JOB_DISABLED_AFTER_BATCH=YES"
FINAL_JOB_STATUS="$("$CLI" jobs show "$JOB_ID" 2>/dev/null | "$PY" -c "import json,sys
try:
    print(json.load(sys.stdin).get('status', ''))
except Exception:
    print('')
" 2>/dev/null)"
log "FINAL_JOB_STATUS=${FINAL_JOB_STATUS:-unknown}"
log "Re-enable for the next batch with: $CLI jobs enable $JOB_ID && $CLI jobs resume $JOB_ID"

log ""
log "===================================================================="
log " Phase 1 batch #3 watcher finished: $(date -u +%FT%TZ)"
log " final_status=$FINAL_STATUS report_saved=$REPORT_FILE"
log "===================================================================="
