#!/usr/bin/env bash
# Run one semi agent scan using isolated test state/cache (not live).
#
# Usage:
#   ./test-semi-agent.sh

set -euo pipefail

cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

TEST_STATE_FILE="data/test/semi_state.json"
TEST_CACHE_DIR="data/test/cache"

mkdir -p data/test data/logs "$TEST_CACHE_DIR"

export SEMI_STATE_FILE="$TEST_STATE_FILE"
export CACHE_DIR="$TEST_CACHE_DIR"

printf 'Test scan using:\n'
printf '  state: %s\n' "$TEST_STATE_FILE"
printf '  cache: %s\n' "$TEST_CACHE_DIR"
printf '  (live state data/semi_state.json is untouched)\n\n'

uv run python run_semi.py --force