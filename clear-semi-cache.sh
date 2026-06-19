#!/usr/bin/env bash
# Reset TEST-ONLY semiconductor agent state and cache.
# Live production state (data/semi_state.json) is never modified.
#
# Usage:
#   ./clear-semi-cache.sh

set -euo pipefail

cd "$(dirname "$0")"

TEST_STATE_FILE="data/test/semi_state.json"
TEST_CACHE_DIR="data/test/cache"
LIVE_STATE_FILE="data/semi_state.json"

mkdir -p data/test "$TEST_CACHE_DIR"

cat > "$TEST_STATE_FILE" <<'JSON'
{
  "sent_alerts": {},
  "daily_alerts": {},
  "trending_watchlist": [],
  "symbol_baselines": {},
  "symbol_theses": {},
  "last_scan": null
}
JSON

if [[ -d "$TEST_CACHE_DIR" ]]; then
  rm -rf "${TEST_CACHE_DIR:?}/"*
fi

printf 'Cleared TEST cache only:\n'
printf '  - %s\n' "$TEST_STATE_FILE"
printf '  - %s/*\n' "$TEST_CACHE_DIR"
printf '\nLive agent untouched:\n'
printf '  - %s\n' "$LIVE_STATE_FILE"
printf '\nRun a test scan:\n'
printf '  %s/test-semi-agent.sh\n' "$(pwd)"