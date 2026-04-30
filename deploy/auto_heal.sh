#!/usr/bin/env bash
# Watchdog: if the bot's last_rebalance is more than $STALE_HOURS old, restart
# the systemd service. Catches the rare case where time.sleep(86400) drifts
# or the bot gets stuck. Designed to be called from a VPS-side cron every hour.
#
# Install: bash deploy/install_auto_heal.sh   (run on the VPS as root)
set -euo pipefail

STATE_FILE="/home/botuser/binance-bot-/data/rotation_state.json"
SERVICE="binance-bot"
STALE_HOURS="${STALE_HOURS:-26}"
LOG="/var/log/binance-bot-auto-heal.log"

if [[ ! -f "$STATE_FILE" ]]; then
    echo "[$(date)] no state file at $STATE_FILE; skipping" >> "$LOG"
    exit 0
fi

LAST_ISO="$(python3 -c "
import json
print(json.load(open('$STATE_FILE'))['last_rebalance'])
" 2>/dev/null || echo "")"

if [[ -z "$LAST_ISO" ]]; then
    echo "[$(date)] could not read last_rebalance; skipping" >> "$LOG"
    exit 0
fi

HOURS_SINCE="$(python3 -c "
from datetime import datetime, timezone
last = datetime.fromisoformat('$LAST_ISO')
print(f\"{(datetime.now(timezone.utc) - last).total_seconds() / 3600:.2f}\")
")"

# Healthy → no action, log occasionally
COMPARE="$(python3 -c "print('1' if float('$HOURS_SINCE') > float('$STALE_HOURS') else '0')")"

if [[ "$COMPARE" == "1" ]]; then
    echo "[$(date)] last_rebalance is ${HOURS_SINCE}h old (>${STALE_HOURS}h) — restarting $SERVICE" >> "$LOG"
    systemctl restart "$SERVICE"
    sleep 5
    echo "[$(date)] restart complete; new status: $(systemctl is-active $SERVICE)" >> "$LOG"
else
    # Light heartbeat in the log (only every Nth check, but cheap regardless)
    echo "[$(date)] healthy — last_rebalance is ${HOURS_SINCE}h old" >> "$LOG"
fi
