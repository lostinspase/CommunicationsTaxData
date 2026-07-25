#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${CTD_APP_DIR:-$HOME/communications-tax-data}"
CURRENT="$(mktemp)"
UPDATED="$(mktemp)"
trap 'rm -f "$CURRENT" "$UPDATED"' EXIT

crontab -l >"$CURRENT" 2>/dev/null || true
sed '/# BEGIN COMMUNICATIONS TAX DATA/,/# END COMMUNICATIONS TAX DATA/d' \
  "$CURRENT" >"$UPDATED"
cat >>"$UPDATED" <<EOF
# BEGIN COMMUNICATIONS TAX DATA
# Server clock is UTC. Refresh jobs share a lock and cannot overlap.
17 6 * * * $APP_DIR/deploy/run-refresh.sh daily >>$APP_DIR/logs/refresh.log 2>&1
37 7 * * 0 $APP_DIR/deploy/run-refresh.sh sst >>$APP_DIR/logs/refresh.log 2>&1
57 8 1 * * $APP_DIR/deploy/run-refresh.sh census >>$APP_DIR/logs/refresh.log 2>&1
@reboot $APP_DIR/deploy/ensure-dashboard.sh >>$APP_DIR/logs/dashboard-supervisor.log 2>&1
*/5 * * * * $APP_DIR/deploy/ensure-dashboard.sh >>$APP_DIR/logs/dashboard-supervisor.log 2>&1
# END COMMUNICATIONS TAX DATA
EOF
crontab "$UPDATED"
echo "Installed CommunicationsTaxData crontab block."
