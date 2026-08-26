#!/usr/bin/env bash
# DB Collector OS - VPS update script.
#
# Steps: record current commit -> backup DB+config -> git pull (fast-forward
# only) -> dependency update -> migration -> restart services -> healthcheck
# -> integrity check.
#
# On failure, the script stops and prints the exact commands to roll back to
# the pre-update commit (see README "Rollback"). Set AUTO_ROLLBACK=1 to have
# it attempt that rollback automatically instead of just printing it.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"

log() { echo "[update] $*"; }
fail() { echo "[update] ERROR: $*" >&2; exit 1; }

AUTO_ROLLBACK="${AUTO_ROLLBACK:-0}"
GIT_BRANCH="${DB_COLLECTOR_BRANCH:-$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo main)}"

PREV_COMMIT="$(git rev-parse HEAD 2>/dev/null || echo unknown)"
log "current commit: $PREV_COMMIT (branch: $GIT_BRANCH)"

rollback_hint() {
    echo "-----------------------------------------------------------------"
    echo "[update] UPDATE FAILED. To roll back manually:"
    echo "  cd $APP_DIR"
    echo "  git checkout $PREV_COMMIT"
    echo "  .venv/bin/pip install -e ."
    echo "  .venv/bin/db-collector migrate"
    echo "  systemctl restart db-collector-scheduler db-collector-worker@1 db-collector-admin"
    echo "A pre-update backup is available under var/backups/ (see the latest"
    echo "timestamped directory printed by backup.sh above)."
    echo "-----------------------------------------------------------------"
}

attempt_rollback() {
    if [ "$AUTO_ROLLBACK" = "1" ] && [ "$PREV_COMMIT" != "unknown" ]; then
        log "AUTO_ROLLBACK=1 -- rolling back to $PREV_COMMIT"
        git checkout "$PREV_COMMIT" || true
        "$APP_DIR/.venv/bin/pip" install -q -e "." || true
        "$APP_DIR/.venv/bin/db-collector" migrate || true
        restart_services || true
        log "rollback attempted; please verify with scripts/healthcheck.sh"
    else
        rollback_hint
    fi
}

restart_services() {
    if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ] && [ "$(id -u)" = "0" ]; then
        log "restarting services"
        systemctl restart db-collector-scheduler.service || true
        for unit in $(systemctl list-units --all 'db-collector-worker@*.service' --no-legend 2>/dev/null | awk '{print $1}'); do
            systemctl restart "$unit" || true
        done
        systemctl restart db-collector-admin.service || true
    else
        log "systemd not available or not root -- restart the scheduler/worker/admin processes manually"
    fi
}

trap 'echo "[update] failed at line $LINENO"; attempt_rollback' ERR

# ---------------------------------------------------------------------------
# 1. backup DB + config
# ---------------------------------------------------------------------------
log "backing up DB + config before updating"
"$APP_DIR/scripts/backup.sh"

# ---------------------------------------------------------------------------
# 2. git pull (fast-forward only)
# ---------------------------------------------------------------------------
if [ -d "$APP_DIR/.git" ]; then
    if ! git diff --quiet || ! git diff --cached --quiet; then
        fail "working tree has uncommitted changes -- commit, stash, or discard them before updating"
    fi
    log "fetching origin/$GIT_BRANCH"
    git fetch origin "$GIT_BRANCH"
    log "fast-forwarding to origin/$GIT_BRANCH"
    git merge --ff-only "origin/$GIT_BRANCH"
    NEW_COMMIT="$(git rev-parse HEAD)"
    log "now at commit: $NEW_COMMIT"
else
    fail "$APP_DIR is not a git repository -- cannot update"
fi

# ---------------------------------------------------------------------------
# 3. dependency update
# ---------------------------------------------------------------------------
log "updating dependencies"
"$APP_DIR/.venv/bin/pip" install -q --upgrade pip
"$APP_DIR/.venv/bin/pip" install -q -e "."

# ---------------------------------------------------------------------------
# 4. migration
# ---------------------------------------------------------------------------
log "applying migrations"
"$APP_DIR/.venv/bin/db-collector" migrate

# ---------------------------------------------------------------------------
# 5. restart services
# ---------------------------------------------------------------------------
restart_services
sleep 2

# ---------------------------------------------------------------------------
# 6. healthcheck + integrity
# ---------------------------------------------------------------------------
log "running healthcheck"
if ! "$APP_DIR/scripts/healthcheck.sh"; then
    fail "healthcheck failed after update"
fi

log "running DB integrity check"
if ! "$APP_DIR/.venv/bin/db-collector" integrity; then
    fail "DB integrity check failed after update"
fi

trap - ERR
log "update complete: $PREV_COMMIT -> $(git rev-parse HEAD)"
