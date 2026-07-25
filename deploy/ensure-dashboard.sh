#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${CTD_APP_DIR:-$HOME/communications-tax-data}"
RUNTIME_DIR="$APP_DIR/runtime"
LOG_DIR="$APP_DIR/logs"
CTD="$APP_DIR/.venv/bin/ctd"
HOST="${CTD_DASHBOARD_HOST:-127.0.0.1}"
PORT="${CTD_DASHBOARD_PORT:-8091}"

mkdir -p "$RUNTIME_DIR" "$LOG_DIR"
exec 9>"$RUNTIME_DIR/dashboard-start.lock"
flock -n 9 || exit 0

if curl --silent --fail --max-time 3 "http://$HOST:$PORT/api/health" >/dev/null; then
  exit 0
fi
if [[ ! -x "$CTD" || ! -r "$APP_DIR/.env" ]]; then
  echo "$(date --iso-8601=seconds) dashboard prerequisites are missing" >&2
  exit 1
fi

cd "$APP_DIR"
nohup "$CTD" serve --host "$HOST" --port "$PORT" \
  >>"$LOG_DIR/dashboard.log" 2>&1 </dev/null &
echo "$(date --iso-8601=seconds) dashboard start requested on $HOST:$PORT"
