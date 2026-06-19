#!/usr/bin/env bash
# Reset semiconductor agent state and file cache.
# Does NOT touch .env or API keys.
#
# Usage:
#   ./clear-semi-cache.sh
#   ~/projects/grok-stocks-alert/clear-semi-cache.sh

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

if [[ -d "$CACHE_DIR" ]]; then
  rm -rf "${CACHE_DIR:?}/"*
fi

printf 'Cleared semi agent cache:\n'
printf '  - %s\n' "$STATE_FILE"
printf '  - %s/*\n' "$CACHE_DIR"
printf '\nRun a test scan:\n'
printf '  %s/test-semi-agent.sh\n' "$(pwd)"