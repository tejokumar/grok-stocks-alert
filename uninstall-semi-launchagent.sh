#!/usr/bin/env bash
# Fully remove the semi agent LaunchAgent (launchd) on macOS.
# Stops the service, unloads it, deletes plist, and stops orphan processes.
# Does NOT delete .env, live state, or the repo.
#
# Usage:
#   ./uninstall-semi-launchagent.sh
#   INSTALL_DIR=~/projects/grok-stocks-alert ./uninstall-semi-launchagent.sh
#
# Also remove launchd log files:
#   ./uninstall-semi-launchagent.sh --purge-logs

set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-$HOME/projects/grok-stocks-alert}"
PLIST_LABEL="com.tejokumar.grok-semi-alerts"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_LABEL}.plist"
GUI_TARGET="gui/$(id -u)/${PLIST_LABEL}"
LOG_OUT="${INSTALL_DIR}/logs/launchd.stdout.log"
LOG_ERR="${INSTALL_DIR}/logs/launchd.stderr.log"
PURGE_LOGS=false

if [[ "${1:-}" == "--purge-logs" ]]; then
  PURGE_LOGS=true
fi

[[ "$(uname -s)" == "Darwin" ]] || { printf 'ERROR: macOS only\n' >&2; exit 1; }

printf 'Uninstalling semi agent LaunchAgent...\n'
printf '  label: %s\n' "$PLIST_LABEL"
printf '  install dir: %s\n\n' "$INSTALL_DIR"

# 1) Stop and unload from launchd (modern + legacy domains)
if launchctl print "$GUI_TARGET" >/dev/null 2>&1; then
  launchctl bootout "gui/$(id -u)" "$PLIST_PATH" 2>/dev/null \
    || launchctl bootout "$GUI_TARGET" 2>/dev/null \
    || true
fi

launchctl disable "$GUI_TARGET" 2>/dev/null || true
launchctl remove "$PLIST_LABEL" 2>/dev/null || true

# 2) Remove plist so it does not reload on next login
if [[ -f "$PLIST_PATH" ]]; then
  rm -f "$PLIST_PATH"
  printf 'Removed plist: %s\n' "$PLIST_PATH"
else
  printf 'Plist not found (already removed): %s\n' "$PLIST_PATH"
fi

# 3) Stop any orphan semi agent processes started outside launchd
stop_orphans() {
  local pid pattern
  for pattern in \
    "${INSTALL_DIR}/start-semi-agent.sh" \
    "${INSTALL_DIR}/run_semi.py" \
    "run_semi.py.*${INSTALL_DIR}"; do
    pids="$(pgrep -f "$pattern" 2>/dev/null || true)"
    if [[ -n "$pids" ]]; then
      while read -r pid; do
        [[ -n "$pid" ]] || continue
        kill "$pid" 2>/dev/null || true
        printf 'Stopped process %s (%s)\n' "$pid" "$pattern"
      done <<< "$pids"
    fi
  done
}

stop_orphans
sleep 1
stop_orphans

# 4) Optional: remove launchd stdout/stderr logs
if [[ "$PURGE_LOGS" == true ]]; then
  rm -f "$LOG_OUT" "$LOG_ERR"
  printf 'Removed launchd logs:\n'
  printf '  - %s\n' "$LOG_OUT"
  printf '  - %s\n' "$LOG_ERR"
else
  printf 'Kept launchd logs (pass --purge-logs to delete):\n'
  printf '  - %s\n' "$LOG_OUT"
  printf '  - %s\n' "$LOG_ERR"
fi

# 5) Verify unload
if launchctl print "$GUI_TARGET" >/dev/null 2>&1; then
  printf '\nWARNING: LaunchAgent still loaded. Try:\n'
  printf '  launchctl bootout gui/$(id -u) %s\n' "$PLIST_PATH"
  exit 1
fi

if [[ -f "$PLIST_PATH" ]]; then
  printf '\nWARNING: Plist still exists at %s\n' "$PLIST_PATH"
  exit 1
fi

printf '\nLaunchAgent fully removed.\n'
printf 'Live agent data untouched:\n'
printf '  - %s/.env\n' "$INSTALL_DIR"
printf '  - %s/data/semi_state.json\n' "$INSTALL_DIR"
printf '\nRe-install later:\n'
printf '  %s/install-semi-launchagent.sh\n' "$INSTALL_DIR"