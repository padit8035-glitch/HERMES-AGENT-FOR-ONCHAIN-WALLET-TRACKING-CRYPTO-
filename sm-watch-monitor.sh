#!/usr/bin/env bash
# Smart Money Watchlist Monitor — cron wrapper
# Configure WATCHLIST_DIR to point to your watchlist project
set -euo pipefail

WATCHLIST_DIR="${WATCHLIST_DIR:-./smart-money-watchlist}"
cd "$WATCHLIST_DIR" || { echo "WATCHLIST_DIR not found: $WATCHLIST_DIR"; exit 1; }
node monitor.js
