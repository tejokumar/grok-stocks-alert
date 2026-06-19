#!/usr/bin/env bash
# Install grok-stocks-alert semiconductor agent on macOS (Mac mini).
# Installer v3.0.0 — uses uv (no system Python / Homebrew required)
#
# Usage (add ?v=3 to bust CDN cache on Mac mini):
#   curl -fsSL "https://raw.githubusercontent.com/tejokumar/grok-stocks-alert/main/install-semi-agent.sh?v=3" | bash
# Or after cloning:
#   cd grok-stocks-alert && ./install-semi-agent.sh

INSTALLER_VERSION="4.0.0-uv"
printf '\n[install] grok-semi-agent installer %s\n' "$INSTALLER_VERSION"
printf '[install] If you do NOT see "%s" above, your Mac is running a cached old installer.\n' "$INSTALLER_VERSION"
printf '[install] Use the inline setup in README or: curl -fsSL ".../mac-mini-setup.sh" | bash\n'

set -euo pipefail

# Re-exec after git pull when someone runs a stale copy from an old clone.
if [[ -n "${BASH_SOURCE[0]:-}" ]] && [[ "${BASH_SOURCE[0]}" != bash ]] && [[ -f "${BASH_SOURCE[0]}" ]]; then
  _script_path="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"
  if grep -q 'PYTHON_BIN\|Python 3\.11+ required' "$_script_path" 2>/dev/null; then
    _repo_dir="$(dirname "$_script_path")"
    if [[ -d "$_repo_dir/.git" ]]; then
      printf '\n[install] Stale installer detected — pulling latest from GitHub...\n'
      git -C "$_repo_dir" fetch origin main
      git -C "$_repo_dir" checkout main
      git -C "$_repo_dir" pull --ff-only origin main
      exec "$_repo_dir/$(basename "${BASH_SOURCE[0]}")" "$@"
    fi
  fi
fi

REPO_URL="${REPO_URL:-https://github.com/tejokumar/grok-stocks-alert.git}"
INSTALL_DIR="${INSTALL_DIR:-$HOME/projects/grok-stocks-alert}"
PYTHON_VERSION="${PYTHON_VERSION:-3.12}"
INSTALL_LAUNCH_AGENT="${INSTALL_LAUNCH_AGENT:-yes}"
UV_BIN="${UV_BIN:-}"

log() { printf '\n[install] %s\n' "$*"; }
warn() { printf '\n[install] WARNING: %s\n' "$*"; }
die() { printf '\n[install] ERROR: %s\n' "$*" >&2; exit 1; }

require_macos() {
  [[ "$(uname -s)" == "Darwin" ]] || die "This installer is for macOS only."
}

ensure_path() {
  export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
}

resolve_uv() {
  ensure_path
  if [[ -n "$UV_BIN" ]] && command -v "$UV_BIN" >/dev/null 2>&1; then
    printf '%s' "$UV_BIN"
    return 0
  fi
  if command -v uv >/dev/null 2>&1; then
    printf '%s' "uv"
    return 0
  fi
  if [[ -x "$HOME/.local/bin/uv" ]]; then
    printf '%s' "$HOME/.local/bin/uv"
    return 0
  fi
  return 1
}

require_uv() {
  local uv_cmd
  if uv_cmd="$(resolve_uv)"; then
    UV_BIN="$uv_cmd"
    log "Using uv: $($UV_BIN --version 2>&1)"
    return
  fi

  log "Installing uv (Python package manager)..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ensure_path

  if uv_cmd="$(resolve_uv)"; then
    UV_BIN="$uv_cmd"
    log "Using uv: $($UV_BIN --version 2>&1)"
    return
  fi

  die "Failed to install uv. Add ~/.local/bin to PATH and retry."
}

clone_or_update_repo() {
  if [[ -d "$INSTALL_DIR/.git" ]]; then
    log "Repo exists at $INSTALL_DIR — pulling latest main"
    git -C "$INSTALL_DIR" fetch origin main
    git -C "$INSTALL_DIR" checkout main
    git -C "$INSTALL_DIR" pull --ff-only origin main
    return
  fi

  if [[ -d "$INSTALL_DIR" ]]; then
    die "$INSTALL_DIR exists but is not a git repo. Set INSTALL_DIR to another path."
  fi

  mkdir -p "$(dirname "$INSTALL_DIR")"
  log "Cloning $REPO_URL into $INSTALL_DIR"
  git clone "$REPO_URL" "$INSTALL_DIR"
  git -C "$INSTALL_DIR" checkout main
}

setup_project() {
  log "Installing Python ${PYTHON_VERSION} and dependencies via uv"
  cd "$INSTALL_DIR"
  ensure_path
  "$UV_BIN" python install "$PYTHON_VERSION"
  if [[ -f uv.lock ]]; then
    "$UV_BIN" sync --frozen
  else
    warn "uv.lock not found — running uv sync without --frozen"
    "$UV_BIN" sync
  fi
  log "Environment ready: $($UV_BIN run python --version 2>&1)"
}

setup_env_file() {
  log "Setting up .env"
  cd "$INSTALL_DIR"
  if [[ ! -f .env ]]; then
    cp .env.example .env
    warn "Created .env from template — add your API keys before starting the agent."
  else
    log ".env already exists — leaving unchanged"
  fi
}

setup_directories() {
  log "Creating runtime directories"
  cd "$INSTALL_DIR"
  mkdir -p data logs data/cache
  if [[ ! -f data/semi_state.json ]]; then
    cat > data/semi_state.json <<'JSON'
{
  "sent_alerts": {},
  "daily_alerts": {},
  "trending_watchlist": [],
  "symbol_baselines": {},
  "symbol_theses": {},
  "last_scan": null
}
JSON
  fi
}

write_start_script() {
  log "Writing start script: $INSTALL_DIR/start-semi-agent.sh"
  cat > "$INSTALL_DIR/start-semi-agent.sh" <<'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
exec uv run python run_semi.py "$@"
SCRIPT
  chmod +x "$INSTALL_DIR/start-semi-agent.sh"
}

write_test_script() {
  log "Writing test script: $INSTALL_DIR/test-semi-agent.sh"
  cat > "$INSTALL_DIR/test-semi-agent.sh" <<'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
uv run python run_semi.py --force
SCRIPT
  chmod +x "$INSTALL_DIR/test-semi-agent.sh"
}

write_clear_cache_script() {
  log "Writing cache reset script: $INSTALL_DIR/clear-semi-cache.sh"
  cat > "$INSTALL_DIR/clear-semi-cache.sh" <<'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
STATE_FILE="data/semi_state.json"
CACHE_DIR="data/cache"
mkdir -p data logs "$CACHE_DIR"
cat > "$STATE_FILE" <<'JSON'
{
  "sent_alerts": {},
  "daily_alerts": {},
  "trending_watchlist": [],
  "symbol_baselines": {},
  "symbol_theses": {},
  "last_scan": null
}
JSON
rm -rf "${CACHE_DIR:?}/"*
printf 'Cleared semi agent cache:\n'
printf '  - %s\n' "$STATE_FILE"
printf '  - %s/*\n' "$CACHE_DIR"
printf '\nRun a test scan:\n'
printf '  %s/test-semi-agent.sh\n' "$(pwd)"
SCRIPT
  chmod +x "$INSTALL_DIR/clear-semi-cache.sh"
}

install_launch_agent() {
  [[ "$INSTALL_LAUNCH_AGENT" == "yes" ]] || { log "Skipping launch agent (INSTALL_LAUNCH_AGENT=$INSTALL_LAUNCH_AGENT)"; return; }

  local plist_label="com.tejokumar.grok-semi-alerts"
  local plist_path="$HOME/Library/LaunchAgents/${plist_label}.plist"
  local log_out="$INSTALL_DIR/logs/launchd.stdout.log"
  local log_err="$INSTALL_DIR/logs/launchd.stderr.log"

  log "Installing LaunchAgent for auto-start on login: $plist_path"
  mkdir -p "$HOME/Library/LaunchAgents" "$INSTALL_DIR/logs"

  cat > "$plist_path" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${plist_label}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${INSTALL_DIR}/start-semi-agent.sh</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${INSTALL_DIR}</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>${log_out}</string>
  <key>StandardErrorPath</key>
  <string>${log_err}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>${HOME}/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
</dict>
</plist>
PLIST

  launchctl bootout "gui/$(id -u)/${plist_label}" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$plist_path"
  launchctl enable "gui/$(id -u)/${plist_label}"
  log "LaunchAgent loaded. Agent starts on login and restarts if it crashes."
}

print_next_steps() {
  cat <<EOF

============================================================
 Semiconductor agent install complete
============================================================

Install path:  $INSTALL_DIR

NEXT STEPS (on your Mac mini):

1) Add API keys to .env:
   nano $INSTALL_DIR/.env

   Required:
   - POLYGON_API_KEY
   - FMP_API_KEY
   - ROIC_API_KEY
   - XAI_API_KEY
   - ANTHROPIC_API_KEY
   - TELEGRAM_BOT_TOKEN
   - TELEGRAM_CHAT_ID

2) Test one scan immediately:
   $INSTALL_DIR/test-semi-agent.sh

   Reset cooldowns/theses before retesting:
   $INSTALL_DIR/clear-semi-cache.sh

3) Run during market hours (waits until 9:15 AM ET):
   $INSTALL_DIR/start-semi-agent.sh

4) Logs:
   $INSTALL_DIR/logs/semi_agent.log
   $INSTALL_DIR/logs/launchd.stdout.log

LaunchAgent controls:
   launchctl kickstart -k gui/\$(id -u)/com.tejokumar.grok-semi-alerts   # restart
   launchctl bootout gui/\$(id -u)/com.tejokumar.grok-semi-alerts          # stop
   launchctl bootstrap gui/\$(id -u) ~/Library/LaunchAgents/com.tejokumar.grok-semi-alerts.plist  # start

Optional env overrides for install:
   INSTALL_DIR=~/other/path/grok-stocks-alert ./install-semi-agent.sh
   INSTALL_LAUNCH_AGENT=no ./install-semi-agent.sh

============================================================
EOF
}

main() {
  require_macos
  require_uv
  clone_or_update_repo
  setup_project
  setup_env_file
  setup_directories
  write_start_script
  write_test_script
  write_clear_cache_script
  install_launch_agent
  print_next_steps
}

main "$@"