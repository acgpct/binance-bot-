#!/usr/bin/env bash
# Wrapper invoked by launchd every Sunday at 18:00.
#  1. (optional) syncs latest state from VPS
#  2. generates a weekly report
#  3. saves the full report to data/weekly_reports/<date>.txt
#  4. posts a macOS notification with the one-line summary
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON="$PROJECT_DIR/.venv/bin/python"
REPORTS_DIR="$PROJECT_DIR/data/weekly_reports"
mkdir -p "$REPORTS_DIR"

cd "$PROJECT_DIR"

# Optional: sync from VPS first if VPS_IP is set in the env or a side file
VPS_IP_FILE="$PROJECT_DIR/data/vps_ip.txt"
if [[ -f "$VPS_IP_FILE" ]]; then
    VPS_IP="$(cat "$VPS_IP_FILE")"
    if [[ -n "${VPS_IP:-}" ]]; then
        bash "$PROJECT_DIR/deploy/sync_from_vps.sh" "$VPS_IP" 2>&1 | tail -3 || \
            echo "(VPS sync failed — continuing with local data)"
    fi
fi

# Run the summary, capture output
DATE_STAMP="$(date +%Y-%m-%d)"
REPORT_FILE="$REPORTS_DIR/${DATE_STAMP}.txt"
"$PYTHON" "$SCRIPT_DIR/weekly_summary.py" > "$REPORT_FILE" 2>&1

# Extract the one-line notification summary (last line starts with NOTIFY:)
NOTIFY_LINE="$(grep '^NOTIFY:' "$REPORT_FILE" | sed 's/^NOTIFY: //')"
# Strip the NOTIFY line from the saved report for cleanliness
grep -v '^NOTIFY:' "$REPORT_FILE" > "${REPORT_FILE}.tmp" && mv "${REPORT_FILE}.tmp" "$REPORT_FILE"

# Post a macOS notification (osascript is built-in, no brew needed)
TITLE="Rotation Bot · Weekly Report"
SUBTITLE="$(date '+%a %d %b')"
osascript -e "display notification \"${NOTIFY_LINE//\"/\\\"}\" with title \"$TITLE\" subtitle \"$SUBTITLE\""

# Also append to a master log so you can scroll through history
echo "" >> "$REPORTS_DIR/all_reports.log"
echo "==== ${DATE_STAMP} ====" >> "$REPORTS_DIR/all_reports.log"
cat "$REPORT_FILE" >> "$REPORTS_DIR/all_reports.log"
