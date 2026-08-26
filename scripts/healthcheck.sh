#!/usr/bin/env bash
# Production healthcheck: scheduler/worker/admin systemd status, SQLite
# integrity, disk space, fetch queue, stale jobs, recent errors.
# Exit code 0 = healthy, 1 = unhealthy. Safe to run from cron/monitoring.
set -uo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"

CLI="$APP_DIR/.venv/bin/db-collector"
if [ ! -x "$CLI" ]; then
    CLI="db-collector"  # fall back to PATH (e.g. inside an already-activated venv)
fi

OVERALL_OK=0

echo "== DB Collector OS healthcheck: $(date -u +%FT%TZ) =="

echo "--- systemd services ---"
if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
    for svc in db-collector-scheduler db-collector-admin; do
        if systemctl list-unit-files "${svc}.service" >/dev/null 2>&1; then
            if systemctl is-active --quiet "$svc"; then
                echo "OK   $svc: active"
            else
                echo "FAIL $svc: $(systemctl is-active "$svc" 2>&1)"
                OVERALL_OK=1
            fi
        else
            echo "SKIP $svc: unit not installed"
        fi
    done

    worker_units="$(systemctl list-units --all 'db-collector-worker@*.service' --no-legend 2>/dev/null | awk '{print $1}')"
    if [ -n "$worker_units" ]; then
        for unit in $worker_units; do
            if systemctl is-active --quiet "$unit"; then
                echo "OK   $unit: active"
            else
                echo "FAIL $unit: $(systemctl is-active "$unit" 2>&1)"
                OVERALL_OK=1
            fi
        done
    else
        echo "SKIP db-collector-worker@*: no worker instances found"
    fi
else
    echo "SKIP systemd checks: systemd is not the running init system on this host"
fi

echo "--- application health (db-collector health) ---"
if HEALTH_JSON="$("$CLI" health 2>&1)"; then
    echo "$HEALTH_JSON"
else
    echo "$HEALTH_JSON"
    echo "FAIL db-collector health reported a problem"
    OVERALL_OK=1
fi

echo "--- disk space ---"
df -h "$APP_DIR" | tail -n +1

echo "== healthcheck result: $([ $OVERALL_OK -eq 0 ] && echo PASS || echo FAIL) =="
exit $OVERALL_OK
