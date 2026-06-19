#!/usr/bin/env bash
# Mac mini setup — new filename to avoid CDN cache on install-semi-agent.sh
# Usage:
#   curl -fsSL "https://raw.githubusercontent.com/tejokumar/grok-stocks-alert/main/mac-mini-setup.sh" | bash

set -euo pipefail

INSTALLER_VERSION="4.0.0-uv"
INSTALL_DIR="${INSTALL_DIR:-$HOME/projects/grok-stocks-alert}"
REPO_URL="${REPO_URL:-https://github.com/tejokumar/grok-stocks-alert.git}"
LEGACY_DIR="${HOME}/grok-stocks-alert"

printf '\n[setup] grok-semi-agent Mac mini setup %s\n' "$INSTALLER_VERSION"

export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

if ! command -v uv >/dev/null 2>&1; then
  printf '[setup] Installing uv...\n'
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

printf '[setup] uv: %s\n' "$(uv --version)"

if [[ -d "$LEGACY_DIR/.git" ]] && [[ ! -d "$INSTALL_DIR/.git" ]]; then
  printf '[setup] Found old install at %s — using it (set INSTALL_DIR to override)\n' "$LEGACY_DIR"
  INSTALL_DIR="$LEGACY_DIR"
fi

mkdir -p "$(dirname "$INSTALL_DIR")"
if [[ -d "$INSTALL_DIR/.git" ]]; then
  printf '[setup] Updating repo at %s\n' "$INSTALL_DIR"
  git -C "$INSTALL_DIR" fetch origin main
  git -C "$INSTALL_DIR" checkout main
  git -C "$INSTALL_DIR" pull --ff-only origin main
else
  printf '[setup] Cloning into %s\n' "$INSTALL_DIR"
  git clone "$REPO_URL" "$INSTALL_DIR"
  git -C "$INSTALL_DIR" checkout main
fi

cd "$INSTALL_DIR"
uv python install 3.12
if [[ -f uv.lock ]]; then
  uv sync --frozen
else
  uv sync
fi

if [[ ! -f .env ]]; then
  cp .env.example .env
  printf '[setup] Created .env — add API keys: nano %s/.env\n' "$INSTALL_DIR"
fi

mkdir -p data logs data/cache

cat > start-semi-agent.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
exec uv run python run_semi.py "$@"
EOF
chmod +x start-semi-agent.sh

cat > test-semi-agent.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
uv run python run_semi.py --force
EOF
chmod +x test-semi-agent.sh
chmod +x clear-semi-cache.sh

printf '\n[setup] Python: %s\n' "$(uv run python --version 2>&1)"
printf '[setup] Done. Next:\n'
printf '  1) nano %s/.env\n' "$INSTALL_DIR"
printf '  2) %s/test-semi-agent.sh\n' "$INSTALL_DIR"