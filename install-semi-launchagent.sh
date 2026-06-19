#!/usr/bin/env bash
# Install or reload the semi agent LaunchAgent (launchd) on macOS.
# Intended for Mac mini / production host — not for dev/CI environments.
# Does NOT touch .env, state files, or run a scan.
#
# Usage:
#   ./install-semi-launchagent.sh
#   INSTALL_DIR=~/projects/grok-stocks-alert ./install-semi-launchagent.sh
#
# Remove LaunchAgent:
#   ./uninstall-semi-launchagent.sh

set -euo pipefail

INSTALL_DIR="$(cd "${INSTALL_DIR:-$HOME/projects/grok-stocks-alert}" && pwd)"
PLIST_LABEL="com.tejokumar.grok-semi-alerts"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_LABEL}.plist"
START_SCRIPT="${INSTALL_DIR}/start-semi-agent.sh"
LOG_DIR="${HOME}/Library/Logs/${PLIST_LABEL}"
LOG_OUT="${LOG_DIR}/stdout.log"
LOG_ERR="${LOG_DIR}/stderr.log"
GUI_DOMAIN="gui/$(id -u)"
GUI_TARGET="${GUI_DOMAIN}/${PLIST_LABEL}"

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

[[ "$(uname -s)" == "Darwin" ]] || die "macOS only"
[[ -f "$START_SCRIPT" ]] || die "start script not found: $START_SCRIPT — git pull && chmod +x start-semi-agent.sh"
chmod +x "$START_SCRIPT"

command -v uv >/dev/null 2>&1 || die "uv not found in PATH — install uv or add ~/.local/bin to PATH"
[[ -f "${INSTALL_DIR}/run_semi.py" ]] || die "run_semi.py not found under $INSTALL_DIR"

mkdir -p "$HOME/Library/LaunchAgents" "$LOG_DIR"
touch "$LOG_OUT" "$LOG_ERR"

cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${PLIST_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>${START_SCRIPT}</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${INSTALL_DIR}</string>
  <key>LimitLoadToSessionType</key>
  <string>Aqua</string>
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
    <key>HOME</key>
    <string>${HOME}</string>
  </dict>
</dict>
</plist>
PLIST

plutil -lint "$PLIST_PATH" >/dev/null || die "Invalid plist — run: plutil -lint $PLIST_PATH"

# Unload any previous registration
launchctl bootout "$GUI_DOMAIN" "$PLIST_PATH" 2>/dev/null || true
launchctl bootout "$GUI_TARGET" 2>/dev/null || true
launchctl unload "$PLIST_PATH" 2>/dev/null || true
launchctl disable "$GUI_TARGET" 2>/dev/null || true

LOAD_METHOD=""
if launchctl bootstrap "$GUI_DOMAIN" "$PLIST_PATH" 2>/dev/null; then
  LOAD_METHOD="bootstrap"
  launchctl enable "$GUI_TARGET" 2>/dev/null || true
elif launchctl load -w "$PLIST_PATH" 2>/dev/null; then
  LOAD_METHOD="load"
else
  printf 'Failed to register LaunchAgent. Diagnostics:\n' >&2
  printf '  plist:   %s\n' "$PLIST_PATH" >&2
  printf '  start:   %s\n' "$START_SCRIPT" >&2
  printf '  workdir: %s\n' "$INSTALL_DIR" >&2
  ls -la "$START_SCRIPT" "$LOG_DIR" >&2 || true
  die "launchctl bootstrap and launchctl load both failed — run on Mac mini GUI session, not SSH/CI"
fi

printf 'LaunchAgent installed (%s):\n' "$LOAD_METHOD"
printf '  plist:  %s\n' "$PLIST_PATH"
printf '  runs:   /bin/bash %s\n' "$START_SCRIPT"
printf '  stdout: %s\n' "$LOG_OUT"
printf '  stderr: %s\n' "$LOG_ERR"
printf '  app log: %s/logs/semi_agent.log\n' "$INSTALL_DIR"
printf '\nControls:\n'
printf '  restart:   launchctl kickstart -k %s\n' "$GUI_TARGET"
printf '  uninstall: %s/uninstall-semi-launchagent.sh\n' "$INSTALL_DIR"
printf '  status:    launchctl print %s\n' "$GUI_TARGET"