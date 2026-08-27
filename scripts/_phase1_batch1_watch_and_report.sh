#!/usr/bin/env bash
# Internal helper for scripts/run_goodsmile_phase1_batch1.sh. Invoked via a
# named `systemd-run` transient unit so it (and its report) survives an SSH
# disconnect even though the actual crawl runs through the
# already-persistent db-collector-worker@1.service, not through this
# process. Polls until the job settles (or a generous timeout), writes a
# full report + evaluates the Phase 1 batch #1 success gate, and always
# disables the job afterward (success or anomaly), per the Phase 1
# "one batch at a time" policy.
#
# Not meant to be run directly by a human -- use
# scripts/run_goodsmile_phase1_batch1.sh, which launches this via systemd-run.
set -uo pipefail  # deliberately no -e: every step below must still run so a report is always produced

APP_DIR="${DB_COLLECTOR_APP_DIR:-/root/tools/db_collector_os}"
JOB_ID="job_prod_figure_official_site"
TIMEOUT_SECONDS="${PHASE1_WATCH_TIMEOUT_SECONDS:-1800}"
POLL_SECONDS="${PHASE1_WATCH_POLL_SECONDS:-15}"
ADMIN_PORT="${DB_COLLECTOR_ADMIN_PORT:-8787}"

cd "$APP_DIR" || { echo "[FATAL] app dir not found: $APP_DIR"; exit 1; }
# `exit` is fine in this file specifically: it only ever runs inside its own
# systemd-run process, never in an operator's interactive shell.

CLI="$APP_DIR/.venv/bin/db-collector"
PY="$APP_DIR/.venv/bin/python"

REPORT_DIR="$APP_DIR/var/reports"
mkdir -p "$REPORT_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
REPORT_FILE="$REPORT_DIR/phase1_batch1_${STAMP}.txt"

log() { echo "$*" | tee -a "$REPORT_FILE"; }

log "===================================================================="
log " Phase 1 batch #1 watcher started: $(date -u +%FT%TZ)"
log " job_id=$JOB_ID timeout=${TIMEOUT_SECONDS}s poll=${POLL_SECONDS}s"
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
"$PY" scripts/_phase1_batch1_report.py "$JOB_ID" 2>&1 | tee -a "$REPORT_FILE"

log ""
log "--- DB integrity ---"
INTEGRITY_OUTPUT="$("$CLI" integrity 2>&1)"
echo "$INTEGRITY_OUTPUT" | tee -a "$REPORT_FILE"

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

# -- success gate ------------------------------------------------------------
LATEST_RUN_ERROR_COUNT="$(grep -oE 'LATEST_RUN_ERROR_COUNT=-?[0-9]+' "$REPORT_FILE" | tail -1 | cut -d= -f2)"
LATEST_RUN_STATUS="$(grep -oE 'LATEST_RUN_STATUS=[a-z_]+' "$REPORT_FILE" | tail -1 | cut -d= -f2)"
BATCH_FETCHED="$(grep -oE 'BATCH_FETCHED=[0-9]+' "$REPORT_FILE" | tail -1 | cut -d= -f2)"
BATCH_INSERTED="$(grep -oE 'BATCH_INSERTED=[0-9]+' "$REPORT_FILE" | tail -1 | cut -d= -f2)"
BATCH_ERRORS="$(grep -oE 'BATCH_ERRORS=[0-9]+' "$REPORT_FILE" | tail -1 | cut -d= -f2)"
OPEN_REVIEW_COUNT="$(grep -oE 'OPEN_REVIEW_COUNT=[0-9]+' "$REPORT_FILE" | tail -1 | cut -d= -f2)"
ENTITY_COUNT="$(grep -oE 'ENTITY_COUNT=[0-9]+' "$REPORT_FILE" | tail -1 | cut -d= -f2)"
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
log " Phase 1 batch #1 -- success gate evaluation"
log "===================================================================="

GATE_FAIL_REASONS=""
INTEGRITY_OK=0
[ "$INTEGRITY_OUTPUT" = "ok" ] && INTEGRITY_OK=1
[ "$INTEGRITY_OK" = "1" ] || GATE_FAIL_REASONS="${GATE_FAIL_REASONS}db_integrity_not_ok;"
[ "$FINAL_STATUS" = "completed" ] || GATE_FAIL_REASONS="${GATE_FAIL_REASONS}job_status_not_completed(${FINAL_STATUS});"
[ "${LATEST_RUN_STATUS:-}" = "completed" ] || GATE_FAIL_REASONS="${GATE_FAIL_REASONS}latest_run_not_completed(${LATEST_RUN_STATUS:-none});"
[ "${BATCH_FETCHED:-0}" -gt 0 ] 2>/dev/null || GATE_FAIL_REASONS="${GATE_FAIL_REASONS}fetched_not_gt_0;"
[ "${BATCH_INSERTED:-0}" -gt 0 ] 2>/dev/null || GATE_FAIL_REASONS="${GATE_FAIL_REASONS}inserted_not_gt_0;"
[ "$SERVICES_OK" = "1" ] || GATE_FAIL_REASONS="${GATE_FAIL_REASONS}services_not_active;"
[ "$ADMIN_CODE" = "200" ] || GATE_FAIL_REASONS="${GATE_FAIL_REASONS}admin_http_not_200(${ADMIN_CODE:-none});"
[ -z "$ENABLED_SAMPLES" ] || GATE_FAIL_REASONS="${GATE_FAIL_REASONS}sample_jobs_enabled(${ENABLED_SAMPLES});"

if [ "${BATCH_FETCHED:-0}" -gt 0 ] 2>/dev/null; then
    ERROR_RATE_OK="$("$PY" -c "print(1 if (${BATCH_ERRORS:-0} / ${BATCH_FETCHED:-1}) <= ${MAX_ERROR_RATE:-0.5} else 0)" 2>/dev/null)"
    [ "${ERROR_RATE_OK:-0}" = "1" ] || GATE_FAIL_REASONS="${GATE_FAIL_REASONS}error_rate_exceeds_max(${BATCH_ERRORS:-0}/${BATCH_FETCHED:-0} > ${MAX_ERROR_RATE:-0.5});"
fi

# "open review not abnormally elevated": a simple, documented heuristic --
# more open reviews than entities collected (or more than 10, whichever is
# larger) is treated as abnormal for a first batch.
ENTITY_COUNT_VAL="${ENTITY_COUNT:-0}"
if [ "$ENTITY_COUNT_VAL" -gt 10 ] 2>/dev/null; then
    REVIEW_BOUND="$ENTITY_COUNT_VAL"
else
    REVIEW_BOUND=10
fi
[ "${OPEN_REVIEW_COUNT:-0}" -le "$REVIEW_BOUND" ] 2>/dev/null || GATE_FAIL_REASONS="${GATE_FAIL_REASONS}open_review_count_elevated(${OPEN_REVIEW_COUNT:-0} > ${REVIEW_BOUND});"

# "HTTP errors not abnormally elevated": 403/404/429 each individually
# bounded by max(5, 20% of fetched) -- a couple of stray 404s on a 30-page
# batch is normal; a wall of them means the discovery/URL logic is wrong
# and the batch should not be treated as a pass even if some pages
# succeeded. Any 5xx at all is flagged too (5xx should be rare/transient).
FETCHED_VAL="${BATCH_FETCHED:-0}"
HTTP_BOUND="$("$PY" -c "print(max(5, int(${FETCHED_VAL:-0} * 0.2)))" 2>/dev/null)"
HTTP_BOUND="${HTTP_BOUND:-5}"
[ "${HTTP_403_COUNT:-0}" -le "$HTTP_BOUND" ] 2>/dev/null || GATE_FAIL_REASONS="${GATE_FAIL_REASONS}http_403_elevated(${HTTP_403_COUNT:-0} > ${HTTP_BOUND});"
[ "${HTTP_404_COUNT:-0}" -le "$HTTP_BOUND" ] 2>/dev/null || GATE_FAIL_REASONS="${GATE_FAIL_REASONS}http_404_elevated(${HTTP_404_COUNT:-0} > ${HTTP_BOUND});"
[ "${HTTP_429_COUNT:-0}" -le "$HTTP_BOUND" ] 2>/dev/null || GATE_FAIL_REASONS="${GATE_FAIL_REASONS}http_429_elevated(${HTTP_429_COUNT:-0} > ${HTTP_BOUND});"
[ "${HTTP_5XX_COUNT:-0}" -eq 0 ] 2>/dev/null || GATE_FAIL_REASONS="${GATE_FAIL_REASONS}http_5xx_present(${HTTP_5XX_COUNT:-0});"

if [ -z "$GATE_FAIL_REASONS" ]; then
    log "GOODSMILE_PHASE1_BATCH1=PASS"
    log "READY_FOR_BATCH2=YES"
else
    log "GOODSMILE_PHASE1_BATCH1=FAIL"
    log "FAIL_REASONS=$GATE_FAIL_REASONS"
    log "READY_FOR_BATCH2=NO"
fi

log ""
log "Disabling job as designed (Phase 1 batch #1 is one batch at a time --"
log "success or anomaly alike -- see docs/first_production_db.md)."
"$CLI" jobs disable "$JOB_ID" 2>&1 | tee -a "$REPORT_FILE"
log "PRODUCTION_JOB_DISABLED_AFTER_BATCH=YES"
log "Re-enable for the next batch with: $CLI jobs enable $JOB_ID && $CLI jobs resume $JOB_ID"

log ""
log "===================================================================="
log " Phase 1 batch #1 watcher finished: $(date -u +%FT%TZ)"
log " final_status=$FINAL_STATUS report_saved=$REPORT_FILE"
log "===================================================================="
