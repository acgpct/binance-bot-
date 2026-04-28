#!/usr/bin/env bash
# Install a launchd job that runs the weekly summary every Sunday at 18:00.
# Run once. Reversible via tools/uninstall_weekly_notification.sh.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LABEL="com.user.binance-bot.weekly-summary"
PLIST_PATH="$HOME/Library/LaunchAgents/${LABEL}.plist"
WRAPPER="$SCRIPT_DIR/run_weekly_summary.sh"

if [[ ! -f "$WRAPPER" ]]; then
    echo "❌ wrapper not found: $WRAPPER"
    exit 1
fi

chmod +x "$WRAPPER"
mkdir -p "$HOME/Library/LaunchAgents"
mkdir -p "$PROJECT_DIR/data/weekly_reports"

# Optional: capture VPS IP for auto-sync
read -r -p "VPS IP for auto-sync (press Enter to skip — you can run sync manually): " VPS_IP
if [[ -n "${VPS_IP:-}" ]]; then
    echo "$VPS_IP" > "$PROJECT_DIR/data/vps_ip.txt"
    echo "✓ saved VPS IP. Note: launchd-triggered scp will need passwordless SSH;"
    echo "  set up an SSH key (ssh-copy-id root@$VPS_IP) or skip the sync part."
fi

# Generate plist
cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL}</string>

  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>${WRAPPER}</string>
  </array>

  <key>StartCalendarInterval</key>
  <dict>
    <key>Weekday</key>
    <integer>0</integer>          <!-- 0 = Sunday -->
    <key>Hour</key>
    <integer>18</integer>
    <key>Minute</key>
    <integer>0</integer>
  </dict>

  <key>RunAtLoad</key>
  <false/>

  <key>StandardOutPath</key>
  <string>${PROJECT_DIR}/data/weekly_reports/launchd.out</string>
  <key>StandardErrorPath</key>
  <string>${PROJECT_DIR}/data/weekly_reports/launchd.err</string>

  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
</dict>
</plist>
EOF

echo "✓ wrote $PLIST_PATH"

# (Re)load it
launchctl unload "$PLIST_PATH" 2>/dev/null || true
launchctl load "$PLIST_PATH"
echo "✓ launchd job loaded"

# Verify
echo
echo "Schedule: every Sunday at 18:00 local time"
echo "Job label: $LABEL"
echo "Logs: $PROJECT_DIR/data/weekly_reports/"
echo
echo "Test it now (without waiting for Sunday):"
echo "  bash $WRAPPER"
echo "  (you should see a macOS notification appear within a few seconds)"
echo
echo "Uninstall:"
echo "  bash $SCRIPT_DIR/uninstall_weekly_notification.sh"
