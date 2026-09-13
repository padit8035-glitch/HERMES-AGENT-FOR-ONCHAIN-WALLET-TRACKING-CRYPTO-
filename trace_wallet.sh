#!/usr/bin/env bash
# Wallet cluster trace — one-shot, runs as cron job
# Usage: ./trace_wallet.sh <wallet_address> [chain]
set -euo pipefail

W="${1:-}"
CHAIN="${2:-robinhood}"
GMGN="${GMGN_PATH:-gmgn-cli}"
CACHE_DIR="${TMPDIR:-/tmp}/wallet-tracker-cache"
TIMEOUT=40

if [ -z "$W" ]; then
  echo "Usage: $0 <wallet_address> [chain]"
  echo "  Example: $0 0xYOUR_WALLET_HERE robinhood"
  exit 1
fi

mkdir -p "$CACHE_DIR"

echo "=== STEP 1: Portfolio Stats ($W) ==="
STATS=$("$GMGN" portfolio stats --chain "$CHAIN" --wallet "$W" --raw 2>&1) || true
if echo "$STATS" | grep -qi "429\|rate.limit\|banned"; then
  echo "❌ GMGN still rate-limited. Stats failed."
  echo "$STATS" | head -3
else
  echo "$STATS"
  CACHE_KEY=$(echo -n "stats-${CHAIN}-${W}" | md5sum | cut -d' ' -f1)
  echo "$STATS" > "$CACHE_DIR/$CACHE_KEY.json"
fi

sleep 5

echo ""
echo "=== STEP 2: Portfolio Activity (recent trades) ==="
ACTIVITY=$("$GMGN" portfolio activity --chain "$CHAIN" --wallet "$W" --limit 30 --raw 2>&1) || true
if echo "$ACTIVITY" | grep -qi "429\|rate.limit\|banned"; then
  echo "❌ GMGN rate-limited on activity"
else
  echo "$ACTIVITY"
fi

echo ""
echo "=== TRACE COMPLETE ==="
