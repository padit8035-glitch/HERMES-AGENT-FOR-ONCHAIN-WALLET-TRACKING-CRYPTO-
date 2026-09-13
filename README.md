# Wallet Tracker

Multi-wallet monitoring toolkit for EVM chains. Polls trades and ERC20 transfers via RPC + GMGN CLI, formats alerts for Telegram delivery.

## Components

| Script | Role |
|--------|------|
| `config.py` | Loads `wallets.json` (wallet addresses, RPC, chain) |
| `bevan_daemon.py` | Long-running daemon: polls every 20s, queues alerts to disk |
| `bevan_deliver.py` | Reads alert queue, outputs for cron delivery |
| `bevan_alerts.py` | One-shot alert runner (cron-friendly) |
| `monitor_wallet.py` | Monitor a single wallet's token activity |
| `multi_wallet_watcher.py` | Real-time multi-wallet watcher with instant Telegram alerts |
| `trace_wallet.sh` | One-shot wallet portfolio trace via GMGN |
| `sm-watch-monitor.sh` | Smart money watchlist cron wrapper |

## Setup

```bash
# 1. Copy example config
cp wallets.example.json wallets.json

# 2. Edit wallets.json — add your wallet addresses
#    NEVER commit wallets.json to git

# 3. Install gmgn-cli (for trade data)
npm install -g gmgn-cli

# 4. Run
python3 bevan_daemon.py          # long-running daemon
python3 bevan_alerts.py          # one-shot (cron)
python3 multi_wallet_watcher.py  # real-time watcher
```

## Requirements

- Python 3.10+
- `gmgn-cli` (npm package)
- Public RPC endpoint (no API key needed for Robinhood Chain)

## ⚠️ Security

- `wallets.json` is in `.gitignore` — never commit it
- No hardcoded wallet addresses in source code
- All wallet data comes from your local config file
- State/cache files are also gitignored
