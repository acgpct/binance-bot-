#!/usr/bin/env bash
# Install a launchd job that runs the DCA bot every Friday at 16:00 local.
# Reversible via tools/uninstall_dca_schedule.sh.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LABEL="com.user.binance-bot.dca"
PLIST_PATH="$HOME/Library/LaunchAgents/${LABEL}.plist"
WRAPPER="$SCRIPT_DIR/run_dca.sh"

if [[ ! -f "$WRAPPER" ]]; then
    echo "❌ wrapper not found: $WRAPPER"
    exit 1
fi

chmod +x "$WRAPPER"
mkdir -p "$HOME/Library/LaunchAgents"
mkdir -p "$PROJECT_DIR/data"

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
    <integer>5</integer>           <!-- 5 = Friday -->
    <key>Hour</key>
    <integer>16</integer>
    <key>Minute</key>
    <integer>0</integer>
  </dict>

  <key>RunAtLoad</key>
  <false/>

  <key>StandardOutPath</key>
  <string>${PROJECT_DIR}/data/dca_launchd.out</string>
  <key>StandardErrorPath</key>
  <string>${PROJECT_DIR}/data/dca_launchd.err</string>

  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
</dict>
</plist>
EOF

echo "✓ wrote $PLIST_PATH"

launchctl unload "$PLIST_PATH" 2>/dev/null || true
launchctl load "$PLIST_PATH"
echo "✓ launchd job loaded"

echo
echo "Schedule: every Friday at 16:00 local time"
echo "Job label: $LABEL"
echo "Logs:      $PROJECT_DIR/data/dca_runs.log"
echo
echo "Test it now (without waiting for Friday):"
echo "  bash $WRAPPER"
echo
echo "Check what it would buy without placing orders:"
echo "  $PROJECT_DIR/.venv/bin/python -m src.dca_bot --dry-run"
echo
echo "Uninstall:"
echo "  bash $SCRIPT_DIR/uninstall_dca_schedule.sh"
