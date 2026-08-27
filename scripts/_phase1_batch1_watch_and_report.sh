#!/usr/bin/env bash
# Internal helper for scripts/phase1_batch1_goodsmile.sh. Invoked via a
# named `systemd-run` transient unit so it (and its report) survives an SSH
# disconnect even though the actual crawl runs through the
# already-persistent db-collector-worker@1.service, not through this
# process. Polls until the job settles (or a generous timeout), writes a
# full report, and always disables the job afterward (success or anomaly),
# per the Phase 1 "one batch at a time" policy.
#
# Not meant to be run directly by a human -- use
# scripts/phase1_batch1_goodsmile.sh, which launches this via systemd-run.
set -uo pipefail  # deliberately no -e: every step below must still run so a report is always produced

APP_DIR="${DB_COLLECTOR_APP_DIR:-/root/tools/db_collector_os}"
JOB_ID="job_prod_figure_official_site"
TIMEOUT_SECONDS="${PHASE1_WATCH_TIMEOUT_SECONDS:-1800}"
POLL_SECONDS="${PHASE1_WATCH_POLL_SECONDS:-15}"

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
"$CLI" integrity 2>&1 | tee -a "$REPORT_FILE"

LATEST_RUN_ERROR_COUNT="$(grep -oE 'LATEST_RUN_ERROR_COUNT=-?[0-9]+' "$REPORT_FILE" | tail -1 | cut -d= -f2)"
LATEST_RUN_STATUS="$(grep -oE 'LATEST_RUN_STATUS=[a-z_]+' "$REPORT_FILE" | tail -1 | cut -d= -f2)"

log ""
if [ "$FINAL_STATUS" = "failed" ] || [ "$FINAL_STATUS" = "timeout" ]; then
    log "ANOMALY: final job status = $FINAL_STATUS -- disabling job for safety."
elif [ "${LATEST_RUN_STATUS:-}" = "failed" ]; then
    log "ANOMALY: latest run_history status = failed -- disabling job for safety."
elif [ -n "${LATEST_RUN_ERROR_COUNT:-}" ] && [ "${LATEST_RUN_ERROR_COUNT:-0}" -gt 0 ] 2>/dev/null; then
    log "Batch settled with $LATEST_RUN_ERROR_COUNT error(s) recorded in the latest run -- disabling job; review before the next batch."
else
    log "Batch completed cleanly -- disabling job as designed (one batch at a time)."
    log "Re-enable for the next batch with: $CLI jobs enable $JOB_ID && $CLI jobs resume $JOB_ID"
fi

"$CLI" jobs disable "$JOB_ID" 2>&1 | tee -a "$REPORT_FILE"

log ""
log "===================================================================="
log " Phase 1 batch #1 watcher finished: $(date -u +%FT%TZ)"
log " final_status=$FINAL_STATUS report_saved=$REPORT_FILE"
log "===================================================================="
