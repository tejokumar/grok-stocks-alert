#!/usr/bin/env bash
# Minimal Mac mini bootstrap — no dependency on cached install script.
# Copy-paste this entire block into Terminal on the Mac mini:
#
#   curl -fsSL "https://raw.githubusercontent.com/tejokumar/grok-stocks-alert/main/bootstrap-mac-mini.sh" | bash

set -euo pipefail

INSTALLER_VERSION="4.0.0-uv"
INSTALL_DIR="${INSTALL_DIR:-$HOME/projects/grok-stocks-alert}"
REPO_URL="${REPO_URL:-https://github.com/tejokumar/grok-stocks-alert.git}"
LEGACY_DIR="${HOME}/grok-stocks-alert"

echo "[bootstrap] grok-semi-agent Mac mini setup ${INSTALLER_VERSION}"
echo "[bootstrap] install path: $INSTALL_DIR"

export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

if ! command -v uv >/dev/null 2>&1; then
  echo "[bootstrap] Installing uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

echo "[bootstrap] uv: $(uv --version)"

if [[ -d "$LEGACY_DIR/.git" ]] && [[ ! -d "$INSTALL_DIR/.git" ]]; then
  echo "[bootstrap] Found old install at $LEGACY_DIR — using it"
  INSTALL_DIR="$LEGACY_DIR"
fi

mkdir -p "$(dirname "$INSTALL_DIR")"
if [[ -d "$INSTALL_DIR/.git" ]]; then
  echo "[bootstrap] Updating existing repo..."
  git -C "$INSTALL_DIR" fetch origin main
  git -C "$INSTALL_DIR" checkout main
  git -C "$INSTALL_DIR" pull --ff-only origin main
else
  echo "[bootstrap] Cloning repo..."
  git clone "$REPO_URL" "$INSTALL_DIR"
fi

cd "$INSTALL_DIR"
uv python install 3.12
uv sync

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "[bootstrap] Created .env — add your API keys: nano $INSTALL_DIR/.env"
fi

mkdir -p data logs
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
chmod +x clear-semi-cache.sh 2>/dev/null || true

echo ""
echo "============================================================"
echo " Bootstrap complete"
echo "============================================================"
echo "  1) nano $INSTALL_DIR/.env"
echo "  2) $INSTALL_DIR/test-semi-agent.sh"
echo "  3) $INSTALL_DIR/start-semi-agent.sh"
echo "============================================================"