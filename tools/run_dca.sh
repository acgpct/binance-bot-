#!/usr/bin/env bash
# Wrapper invoked by launchd every Friday at 16:00 (after market close in UTC-friendly time).
# Runs the DCA bot once and posts a desktop notification with the result.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON="$PROJECT_DIR/.venv/bin/python"
LOG_FILE="$PROJECT_DIR/data/dca_runs.log"

cd "$PROJECT_DIR"

DATE_STAMP="$(date +%Y-%m-%dT%H:%M:%S)"
{
    echo ""
    echo "==== ${DATE_STAMP} ===="
    "$PYTHON" -m src.dca_bot 2>&1 || echo "DCA run failed with exit $?"
} | tee -a "$LOG_FILE"

# Pull the last summary line (the "Bought ..." or "[dry-run]" or error)
LAST_LINE="$(tail -20 "$LOG_FILE" | grep -E '✓ Bought|\[dry-run\]|buy failed' | tail -1 || echo "DCA run complete")"

osascript -e "display notification \"${LAST_LINE//\"/\\\"}\" with title \"DCA Bot\" subtitle \"$(date '+%a %d %b')\""
