#!/usr/bin/env bash
# Install or reload the semi agent LaunchAgent (launchd) on macOS.
# Does NOT touch .env, state files, or run a scan.
#
# Usage:
#   ./install-semi-launchagent.sh
#   INSTALL_DIR=~/projects/grok-stocks-alert ./install-semi-launchagent.sh
#
# Remove LaunchAgent:
#   ./uninstall-semi-launchagent.sh

set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-$HOME/projects/grok-stocks-alert}"
PLIST_LABEL="com.tejokumar.grok-semi-alerts"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_LABEL}.plist"
START_SCRIPT="${INSTALL_DIR}/start-semi-agent.sh"
LOG_OUT="${INSTALL_DIR}/logs/launchd.stdout.log"
LOG_ERR="${INSTALL_DIR}/logs/launchd.stderr.log"

[[ "$(uname -s)" == "Darwin" ]] || { printf 'ERROR: macOS only\n' >&2; exit 1; }
[[ -x "$START_SCRIPT" ]] || {
  printf 'ERROR: start script not found: %s\n' "$START_SCRIPT" >&2
  printf 'Run from repo root or set INSTALL_DIR.\n' >&2
  exit 1
}

mkdir -p "$HOME/Library/LaunchAgents" "${INSTALL_DIR}/logs"

cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${PLIST_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${START_SCRIPT}</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${INSTALL_DIR}</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>${LOG_OUT}</string>
  <key>StandardErrorPath</key>
  <string>${LOG_ERR}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>${HOME}/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
</dict>
</plist>
PLIST

launchctl bootout "gui/$(id -u)/${PLIST_LABEL}" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"
launchctl enable "gui/$(id -u)/${PLIST_LABEL}"

printf 'LaunchAgent installed:\n'
printf '  plist:  %s\n' "$PLIST_PATH"
printf '  runs:   %s\n' "$START_SCRIPT"
printf '  stdout: %s\n' "$LOG_OUT"
printf '  stderr: %s\n' "$LOG_ERR"
printf '\nControls:\n'
printf '  restart:  launchctl kickstart -k gui/$(id -u)/%s\n' "$PLIST_LABEL"
printf '  uninstall: %s/uninstall-semi-launchagent.sh\n' "$INSTALL_DIR"
printf '  status:   launchctl print gui/$(id -u)/%s\n' "$PLIST_LABEL"