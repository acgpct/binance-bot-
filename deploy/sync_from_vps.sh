#!/usr/bin/env bash
# Pull the bot's state files from your VPS to your Mac so the dashboard shows live data.
# Run this before opening the dashboard (or whenever you want a fresh chart).
#
# Usage:
#   bash deploy/sync_from_vps.sh                    # uses VPS_IP env var
#   bash deploy/sync_from_vps.sh 165.232.105.26     # explicit IP
#   VPS_IP=165.232.105.26 bash deploy/sync_from_vps.sh

set -euo pipefail

VPS_IP="${1:-${VPS_IP:-}}"
if [[ -z "$VPS_IP" ]]; then
    echo "Usage: $0 <vps-ip>"
    echo "Or set VPS_IP env var (e.g. add 'export VPS_IP=...' to your shell rc)"
    exit 1
fi

REMOTE="root@${VPS_IP}:/home/botuser/binance-bot-/data"
LOCAL_DIR="$(cd "$(dirname "$0")/.." && pwd)/data"
mkdir -p "$LOCAL_DIR"

echo "==> Pulling state from ${VPS_IP}..."
scp "${REMOTE}/rotation_state.json" "${LOCAL_DIR}/" || echo "  (no rotation_state.json yet)"
scp "${REMOTE}/equity_history.csv"  "${LOCAL_DIR}/" 2>/dev/null \
    || echo "  (no equity_history.csv yet — will appear after first VPS rebalance)"

echo "==> Done. Refresh the dashboard tab."
