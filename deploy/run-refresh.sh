#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${CTD_APP_DIR:-$HOME/communications-tax-data}"
RUNTIME_DIR="$APP_DIR/runtime"
LOG_DIR="$APP_DIR/logs"
CTD="$APP_DIR/.venv/bin/ctd"
MODE="${1:-daily}"

mkdir -p "$RUNTIME_DIR" "$LOG_DIR" "$APP_DIR/reports"
exec 9>"$RUNTIME_DIR/refresh.lock"
if ! flock -n 9; then
  echo "$(date --iso-8601=seconds) refresh skipped: another refresh is active"
  exit 0
fi

if [[ ! -x "$CTD" ]]; then
  echo "CTD executable is missing: $CTD" >&2
  exit 1
fi
if [[ ! -r "$APP_DIR/.env" ]]; then
  echo "Production environment file is missing: $APP_DIR/.env" >&2
  exit 1
fi

cd "$APP_DIR"
echo "$(date --iso-8601=seconds) refresh started: $MODE"

case "$MODE" in
  daily)
    "$CTD" seed-catalog
    "$CTD" collect --collector federal
    "$CTD" collect --collector monitor
    "$CTD" benchmark-sync
    ;;
  sst)
    "$CTD" seed-catalog
    "$CTD" collect --collector sst
    ;;
  census)
    "$CTD" collect --collector census
    ;;
  *)
    echo "Unknown refresh mode: $MODE" >&2
    exit 2
    ;;
esac

"$CTD" compare
"$CTD" report --output-dir "$APP_DIR/reports"
echo "$(date --iso-8601=seconds) refresh completed: $MODE"
