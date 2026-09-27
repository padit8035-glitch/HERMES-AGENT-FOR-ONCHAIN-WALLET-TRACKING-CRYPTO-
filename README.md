# Wallet Tracker

Multi-wallet on-chain monitoring toolkit for EVM chains. Polls token trades and ERC20 transfers over JSON-RPC plus GMGN CLI, formats alerts, and hands them to a delivery script for Telegram. Built to track a cluster of wallets and react to activity within a poll cycle.

**Read-only.** No keys, no signing, no transaction submission.

## Components

| Script | Role |
| --- | --- |
| `config.py` | Loads `wallets.json` (addresses, RPC endpoint, chain) |
| `bevan_daemon.py` | Long-running daemon: polls on an interval, queues alerts to disk |
| `bevan_deliver.py` | Reads the alert queue and emits output for cron delivery |
| `bevan_alerts.py` | One-shot alert runner (cron-friendly) |
| `monitor_wallet.py` | Single-wallet token activity monitor |
| `multi_wallet_watcher.py` | Multi-wallet watcher with instant Telegram alerts |
| `trace_wallet.sh` | One-shot wallet portfolio trace via GMGN |
| `sm-watch-monitor.sh` | Smart-money watchlist cron wrapper |
| `wallets.example.json` | Config template — copy, do not commit the real one |

The daemon/deliver split exists so polling and delivery are independently restartable: if Telegram is down, alerts stay queued on disk and drain on the next successful run instead of being lost.

## Setup

```bash
cp wallets.example.json wallets.json   # then add your addresses
npm install -g gmgn-cli                 # trade data source

python3 bevan_alerts.py                # one-shot, good for a first check
python3 bevan_daemon.py                # long-running
```

## Deploy

Run the daemon under systemd and the deliver script from cron, or both from cron if you prefer one moving part.

```cron
* * * * * cd /opt/wallet-tracker && python3 bevan_alerts.py | /opt/wallet-tracker/send.sh
```

## Requirements

- Python 3.10+ (standard library only — no third-party Python packages)
- `gmgn-cli` (npm) for trade data
- A public RPC endpoint

## Security

- `wallets.json`, state, queue, and cache files are git-ignored — never commit them
- No wallet addresses or RPC keys are hardcoded in source
- The toolkit only reads chain data

## Notes

- Config values in `wallets.example.json` are placeholders.

MIT licensed.
