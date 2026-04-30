#!/usr/bin/env bash
# Remove the auto-sync launchd job.
set -euo pipefail

LABEL="com.user.binance-bot.auto-sync"
PLIST_PATH="$HOME/Library/LaunchAgents/${LABEL}.plist"

if [[ -f "$PLIST_PATH" ]]; then
    launchctl unload "$PLIST_PATH" 2>/dev/null || true
    rm -f "$PLIST_PATH"
    echo "✓ removed $PLIST_PATH"
else
    echo "(no plist installed at $PLIST_PATH — nothing to remove)"
fi
