#!/usr/bin/env bash
# Install a launchd job that pulls VPS state to your Mac every 30 minutes.
# After this, the dashboard is always fresh — no more manual sync_from_vps.sh.
#
# Reversible via tools/uninstall_auto_sync.sh.
#
# Prerequisites:
#   1. The VPS IP is recorded in data/vps_ip.txt (created on first run if missing)
#   2. SSH key auth is set up to root@VPS so scp doesn't prompt for password.
#      If you haven't done this yet:
#        ssh-keygen -t ed25519             # if you don't have a key
#        ssh-copy-id root@<your-vps-ip>    # one-time, prompts for password
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LABEL="com.user.binance-bot.auto-sync"
PLIST_PATH="$HOME/Library/LaunchAgents/${LABEL}.plist"
WRAPPER="$SCRIPT_DIR/run_auto_sync.sh"
VPS_IP_FILE="$PROJECT_DIR/data/vps_ip.txt"

if [[ ! -f "$WRAPPER" ]]; then
    echo "❌ wrapper not found: $WRAPPER"
    exit 1
fi
chmod +x "$WRAPPER"

# Ask for VPS IP if not already saved
if [[ ! -f "$VPS_IP_FILE" ]]; then
    read -r -p "VPS IP (e.g. 165.232.105.26): " VPS_IP
    echo "$VPS_IP" > "$VPS_IP_FILE"
    echo "✓ saved VPS IP to $VPS_IP_FILE"
fi
VPS_IP="$(cat "$VPS_IP_FILE")"

# Check SSH key auth works (no password prompt)
echo "==> Testing passwordless SSH to root@${VPS_IP}..."
if ssh -o BatchMode=yes -o ConnectTimeout=5 "root@${VPS_IP}" 'echo ok' &>/dev/null; then
    echo "  ✓ passwordless SSH works"
else
    echo "  ⚠️  Could not connect without a password."
    echo "     You need to set up SSH key auth so scp can run unattended:"
    echo
    echo "       ssh-keygen -t ed25519       # if you don't already have ~/.ssh/id_ed25519"
    echo "       ssh-copy-id root@${VPS_IP}  # one-time, will prompt for VPS root password"
    echo
    echo "     Then re-run this installer."
    exit 1
fi

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

  <key>StartInterval</key>
  <integer>1800</integer>          <!-- every 30 minutes -->

  <key>RunAtLoad</key>
  <true/>

  <key>StandardOutPath</key>
  <string>${PROJECT_DIR}/data/auto_sync.out</string>
  <key>StandardErrorPath</key>
  <string>${PROJECT_DIR}/data/auto_sync.err</string>

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
echo "✓ auto-sync launchd job loaded (runs every 30 min, plus on every login)"

echo
echo "Watch it: tail -f $PROJECT_DIR/data/auto_sync.log"
echo "Uninstall: bash $SCRIPT_DIR/uninstall_auto_sync.sh"
