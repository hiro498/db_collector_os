#!/usr/bin/env bash
# DB Collector OS - first-time (or repeat) VPS installer.
#
# Assumes this script is run from inside the already-cloned repository (the
# expected production path is /root/tools/db_collector_os, matching the
# systemd unit files under systemd/). Safe to re-run: it never deletes an
# existing .env, an existing SQLite DB, or existing data under var/.
#
# Steps: OS precheck -> Python check -> venv -> deps -> directories ->
# DB migration -> permissions -> systemd unit install -> daemon-reload ->
# enable -> start -> healthcheck -> DB integrity check.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"

log() { echo "[install] $*"; }
fail() { echo "[install] ERROR: $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# 1. OS precheck
# ---------------------------------------------------------------------------
log "OS precheck"
if [ "$(uname -s)" != "Linux" ]; then
    fail "this installer targets Linux VPS hosts (found: $(uname -s))"
fi
HAS_SYSTEMD=1
if ! command -v systemctl >/dev/null 2>&1 || [ ! -d /run/systemd/system ]; then
    log "WARNING: systemd is not the running init system here -- systemd steps will be skipped (you can still run the CLI manually)"
    HAS_SYSTEMD=0
fi

# ---------------------------------------------------------------------------
# 2. Python check
# ---------------------------------------------------------------------------
log "Python check"
PYTHON_BIN=""
for candidate in python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
        PYTHON_BIN="$candidate"
        break
    fi
done
[ -n "$PYTHON_BIN" ] || fail "python3.10+ not found on this host"

PY_OK=$("$PYTHON_BIN" -c 'import sys; print(1 if sys.version_info >= (3, 10) else 0)')
[ "$PY_OK" = "1" ] || fail "$PYTHON_BIN is older than the required 3.10+"
log "using $($PYTHON_BIN --version)"

# ---------------------------------------------------------------------------
# 3. venv
# ---------------------------------------------------------------------------
log "virtualenv"
if [ ! -d "$APP_DIR/.venv" ]; then
    "$PYTHON_BIN" -m venv "$APP_DIR/.venv"
    log "created .venv"
else
    log ".venv already exists, reusing it"
fi
VENV_PY="$APP_DIR/.venv/bin/python"
VENV_PIP="$APP_DIR/.venv/bin/pip"

# ---------------------------------------------------------------------------
# 4. dependency install
# ---------------------------------------------------------------------------
log "installing dependencies (this may take a minute)"
"$VENV_PIP" install -q --upgrade pip
INSTALL_EXTRAS="${DB_COLLECTOR_INSTALL_DEV:-0}"
if [ "$INSTALL_EXTRAS" = "1" ]; then
    "$VENV_PIP" install -q -e ".[dev]"
else
    "$VENV_PIP" install -q -e "."
fi
log "dependencies installed"

# ---------------------------------------------------------------------------
# 5. directories + .env
# ---------------------------------------------------------------------------
log "creating runtime directories"
mkdir -p "$APP_DIR/var/logs" "$APP_DIR/var/checkpoints" "$APP_DIR/var/backups"

if [ ! -f "$APP_DIR/.env" ]; then
    cp "$APP_DIR/.env.example" "$APP_DIR/.env"
    log "created .env from .env.example (edit it to customize; never commit it)"
else
    log ".env already exists, leaving it untouched"
fi

CLI="$VENV_PY -m db_collector_os.cli"

# ---------------------------------------------------------------------------
# 6. DB migration
# ---------------------------------------------------------------------------
log "applying database migrations"
$CLI migrate

log "syncing job definitions from config/jobs/*.yaml"
$CLI jobs sync || log "WARNING: jobs sync reported an issue (check config/jobs/*.yaml)"

# ---------------------------------------------------------------------------
# 7. permissions
# ---------------------------------------------------------------------------
log "setting permissions"
chmod 600 "$APP_DIR/.env" 2>/dev/null || true
chmod -R go-w "$APP_DIR/var" 2>/dev/null || true
find "$APP_DIR/scripts" -name '*.sh' -exec chmod +x {} \;

# ---------------------------------------------------------------------------
# 8. systemd unit install
# ---------------------------------------------------------------------------
if [ "$HAS_SYSTEMD" = "1" ] && [ "$(id -u)" = "0" ]; then
    log "installing systemd units"
    install -m 644 "$APP_DIR/systemd/db-collector-scheduler.service" /etc/systemd/system/
    install -m 644 "$APP_DIR/systemd/db-collector-worker@.service" /etc/systemd/system/
    install -m 644 "$APP_DIR/systemd/db-collector-admin.service" /etc/systemd/system/

    log "daemon-reload"
    systemctl daemon-reload

    log "enable + start scheduler, worker@1, admin"
    systemctl enable --now db-collector-scheduler.service
    systemctl enable --now db-collector-worker@1.service
    systemctl enable --now db-collector-admin.service
    log "enabled services will now auto-start on VPS reboot"
elif [ "$HAS_SYSTEMD" = "1" ]; then
    log "WARNING: not running as root -- skipping systemd unit install. Re-run with sudo/root to install services, or run 'db-collector scheduler run' / 'worker run' / 'admin serve' manually."
else
    log "skipping systemd step (no systemd on this host)"
fi

# ---------------------------------------------------------------------------
# 9. healthcheck + integrity
# ---------------------------------------------------------------------------
log "waiting a moment for services to settle"
sleep 2

log "running healthcheck"
if ! "$APP_DIR/scripts/healthcheck.sh"; then
    log "WARNING: healthcheck reported issues -- see output above"
fi

log "running DB integrity check"
$CLI integrity

log "install complete."
log "Admin UI listens on the host:port configured in config/default.yaml / .env (default: 127.0.0.1:8787)"
log "Try: $APP_DIR/.venv/bin/db-collector status"
