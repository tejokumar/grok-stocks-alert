#!/usr/bin/env bash
# Run the live semiconductor agent (market hours scheduler).
#
# Usage:
#   ./start-semi-agent.sh
#   ./start-semi-agent.sh --force

set -euo pipefail

cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

exec uv run python run_semi.py "$@"