#!/usr/bin/env bash
# Install grok-stocks-alert semiconductor agent on macOS (Mac mini).
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/tejokumar/grok-stocks-alert/main/install-semi-agent.sh | bash
# Or after cloning:
#   cd grok-stocks-alert && ./install-semi-agent.sh

set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/tejokumar/grok-stocks-alert.git}"
INSTALL_DIR="${INSTALL_DIR:-$HOME/projects/grok-stocks-alert}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
INSTALL_LAUNCH_AGENT="${INSTALL_LAUNCH_AGENT:-yes}"

log() { printf '\n[install] %s\n' "$*"; }
warn() { printf '\n[install] WARNING: %s\n' "$*"; }
die() { printf '\n[install] ERROR: %s\n' "$*" >&2; exit 1; }

require_macos() {
  [[ "$(uname -s)" == "Darwin" ]] || die "This installer is for macOS only."
}

python_version_ok() {
  local bin="$1"
  command -v "$bin" >/dev/null 2>&1 || return 1
  "$bin" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY
}

find_python() {
  if [[ "$PYTHON_BIN" != "python3" ]] && python_version_ok "$PYTHON_BIN"; then
    printf '%s' "$PYTHON_BIN"
    return 0
  fi

  local candidates=(
    python3.13 python3.12 python3.11
    /opt/homebrew/bin/python3.13
    /opt/homebrew/bin/python3.12
    /opt/homebrew/bin/python3.11
    /opt/homebrew/bin/python3
    /usr/local/bin/python3.13
    /usr/local/bin/python3.12
    /usr/local/bin/python3.11
    /usr/local/bin/python3
    python3
  )

  local candidate
  for candidate in "${candidates[@]}"; do
    if python_version_ok "$candidate"; then
      printf '%s' "$candidate"
      return 0
    fi
  done
  return 1
}

install_python_with_brew() {
  command -v brew >/dev/null 2>&1 || return 1
  log "Installing Python 3.12 via Homebrew (may take a few minutes)..."
  brew install python@3.12
  brew link python@3.12 --overwrite --force 2>/dev/null || true
}

require_python() {
  local found
  if found="$(find_python)"; then
    PYTHON_BIN="$found"
    log "Using Python: $PYTHON_BIN ($($PYTHON_BIN --version 2>&1))"
    return
  fi

  warn "Python 3.11+ not found on this Mac."
  if command -v python3 >/dev/null 2>&1; then
    warn "Default python3 is: $(python3 --version 2>&1)"
  fi

  if command -v brew >/dev/null 2>&1; then
    install_python_with_brew || die "Homebrew Python install failed."
    if found="$(find_python)"; then
      PYTHON_BIN="$found"
      log "Using Python: $PYTHON_BIN ($($PYTHON_BIN --version 2>&1))"
      return
    fi
  fi

  die "$(cat <<'EOF'
Python 3.11+ required.

On your Mac mini, run ONE of the following, then re-run this installer:

  # Option A — Homebrew (recommended)
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  brew install python@3.12
  echo 'export PATH="/opt/homebrew/bin:$PATH"' >> ~/.zprofile
  source ~/.zprofile
  curl -fsSL https://raw.githubusercontent.com/tejokumar/grok-stocks-alert/main/install-semi-agent.sh | bash

  # Option B — if Python 3.12 already installed via brew
  PYTHON_BIN=/opt/homebrew/bin/python3.12 bash -c "$(curl -fsSL https://raw.githubusercontent.com/tejokumar/grok-stocks-alert/main/install-semi-agent.sh)"
EOF
)"
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

setup_venv() {
  log "Creating virtual environment"
  cd "$INSTALL_DIR"
  if [[ ! -d .venv ]]; then
    "$PYTHON_BIN" -m venv .venv
  fi
  # shellcheck disable=SC1091
  source .venv/bin/activate
  python -m pip install --upgrade pip
  pip install -r requirements.txt
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
source .venv/bin/activate
exec python run_semi.py "$@"
SCRIPT
  chmod +x "$INSTALL_DIR/start-semi-agent.sh"
}

write_test_script() {
  log "Writing test script: $INSTALL_DIR/test-semi-agent.sh"
  cat > "$INSTALL_DIR/test-semi-agent.sh" <<'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
source .venv/bin/activate
python run_semi.py --force
SCRIPT
  chmod +x "$INSTALL_DIR/test-semi-agent.sh"
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
    <string>/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
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
  require_python
  clone_or_update_repo
  setup_venv
  setup_env_file
  setup_directories
  write_start_script
  write_test_script
  install_launch_agent
  print_next_steps
}

main "$@"