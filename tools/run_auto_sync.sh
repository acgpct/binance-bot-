#!/usr/bin/env bash
# Wrapper for the auto-sync launchd job.
# Pulls bot state from VPS to Mac every 30 minutes so the dashboard
# always shows fresh data without you having to run sync_from_vps.sh manually.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SYNC="$PROJECT_DIR/deploy/sync_from_vps.sh"
VPS_IP_FILE="$PROJECT_DIR/data/vps_ip.txt"
LOG="$PROJECT_DIR/data/auto_sync.log"

if [[ ! -f "$VPS_IP_FILE" ]]; then
    echo "[$(date)] no VPS IP configured; skipping" >> "$LOG"
    exit 0
fi
VPS_IP="$(cat "$VPS_IP_FILE")"

# Run sync, log result. Continue silently on failure (transient network issues etc.)
{
    echo "[$(date)] syncing from $VPS_IP..."
    bash "$SYNC" "$VPS_IP" 2>&1 | tail -3
} >> "$LOG" 2>&1 || true
