#!/usr/bin/env bash
# Install a VPS-side cron that runs deploy/auto_heal.sh hourly.
# Run on the VPS as root after `git pull` of the latest code.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
HEAL_SCRIPT="$SCRIPT_DIR/auto_heal.sh"
CRON_FILE="/etc/cron.d/binance-bot-auto-heal"

if [[ ! -f "$HEAL_SCRIPT" ]]; then
    echo "❌ heal script not found: $HEAL_SCRIPT"
    exit 1
fi

chmod +x "$HEAL_SCRIPT"
touch /var/log/binance-bot-auto-heal.log
chmod 644 /var/log/binance-bot-auto-heal.log

cat > "$CRON_FILE" <<EOF
# Watch the rotation bot's last_rebalance timestamp; restart the service
# if it's been > 26h. Runs hourly. Logs to /var/log/binance-bot-auto-heal.log
# Installed by deploy/install_auto_heal.sh
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

15 * * * * root ${HEAL_SCRIPT} >/dev/null 2>&1
EOF

chmod 644 "$CRON_FILE"
echo "✓ wrote $CRON_FILE"
echo "  (runs at minute 15 of every hour)"
echo
echo "Tail logs to verify: tail -f /var/log/binance-bot-auto-heal.log"
echo "Disable: rm $CRON_FILE"
echo
echo "Test it now (does nothing harmful — only restarts if Late):"
echo "  bash $HEAL_SCRIPT && tail -3 /var/log/binance-bot-auto-heal.log"
