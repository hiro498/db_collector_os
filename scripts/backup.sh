#!/usr/bin/env bash
# Back up the SQLite DB, config, and job definitions with a timestamp.
# Safe to run while the scheduler/worker are active (uses `sqlite3 .backup`,
# which is WAL-safe, when the sqlite3 CLI is available; otherwise falls back
# to a plain file copy).
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"

# shellcheck disable=SC1091
[ -f .env ] && set -a && source .env && set +a

DB_COLLECTOR_HOME="${DB_COLLECTOR_HOME:-$APP_DIR/var}"
DB_COLLECTOR_DB_PATH="${DB_COLLECTOR_DB_PATH:-db_collector.sqlite3}"
case "$DB_COLLECTOR_DB_PATH" in
    /*) DB_PATH="$DB_COLLECTOR_DB_PATH" ;;
    *) DB_PATH="$DB_COLLECTOR_HOME/$DB_COLLECTOR_DB_PATH" ;;
esac

BACKUP_ROOT="${DB_COLLECTOR_BACKUP_DIR:-$DB_COLLECTOR_HOME/backups}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="$BACKUP_ROOT/$STAMP"
mkdir -p "$DEST"

echo "[backup] destination: $DEST"

if [ -f "$DB_PATH" ]; then
    if command -v sqlite3 >/dev/null 2>&1; then
        echo "[backup] sqlite3 .backup -> db_collector.sqlite3"
        sqlite3 "$DB_PATH" ".backup '$DEST/db_collector.sqlite3'"
    else
        echo "[backup] sqlite3 CLI not found, falling back to file copy"
        cp -p "$DB_PATH" "$DEST/db_collector.sqlite3"
    fi
else
    echo "[backup] no DB found at $DB_PATH yet, skipping DB backup"
fi

if [ -d "$APP_DIR/config" ]; then
    echo "[backup] config/ -> config/"
    cp -r "$APP_DIR/config" "$DEST/config"
fi

if [ -f "$APP_DIR/.env" ]; then
    echo "[backup] .env -> .env"
    cp -p "$APP_DIR/.env" "$DEST/.env"
fi

echo "$STAMP" > "$DEST/BACKUP_META.txt"
echo "git_commit=$(git -C "$APP_DIR" rev-parse HEAD 2>/dev/null || echo unknown)" >> "$DEST/BACKUP_META.txt"

# Keep the most recent N backups (default 14); prune older ones.
KEEP="${DB_COLLECTOR_BACKUP_KEEP:-14}"
mkdir -p "$BACKUP_ROOT"
ls -1dt "$BACKUP_ROOT"/*/ 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -rf

echo "[backup] done: $DEST"
