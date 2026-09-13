#!/usr/bin/env python3
"""Monitor a specific wallet for token activity (configurable via wallets.json)."""
import json, subprocess, sys, os
from datetime import datetime
from config import load_wallets, BASE_DIR

RPC, CHAIN, WALLETS, _ = load_wallets()

# Use the first wallet with track_trades=True, or override with --wallet CLI arg
def get_target_wallet():
    if "--wallet" in sys.argv:
        idx = sys.argv.index("--wallet")
        if idx + 1 < len(sys.argv):
            return sys.argv[idx + 1]
    for label, (addr, track) in WALLETS.items():
        if track:
            return addr
    return None

WALLET = get_target_wallet()
if not WALLET:
    print("No wallet to monitor. Set one in wallets.json or pass --wallet <addr>")
    sys.exit(1)

TOKEN = os.environ.get("MONITOR_TOKEN", "")  # optional: filter by token contract
STATE = os.path.join(BASE_DIR, "revaz_state.json")

# Load last known state
last = {}
if os.path.exists(STATE):
    with open(STATE) as f:
        last = json.load(f)

last_tx = last.get("last_tx_hash", "")
last_count = last.get("activity_count", 0)

# Fetch current activity
cmd = ["gmgn-cli", "portfolio", "activity", "--chain", CHAIN, "--wallet", WALLET, "--limit", "10"]
if TOKEN:
    cmd += ["--token", TOKEN]
r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
if r.returncode != 0:
    sys.exit(0)  # silent fail

data = json.loads(r.stdout)
activities = data.get("activities", [])

if not activities:
    sys.exit(0)  # no activity

new_count = len(activities)
first_tx = activities[0].get("tx_hash", "")

# No change
if first_tx == last_tx:
    sys.exit(0)

# Find truly new activities (not seen before)
seen = set(last.get("seen_txs", []))
new_activities = [a for a in activities if a["tx_hash"] not in seen]

if not new_activities:
    if new_count != last_count:
        with open(STATE, "w") as f:
            json.dump({"last_tx_hash": first_tx, "activity_count": new_count, "seen_txs": list(seen)}, f)
    sys.exit(0)

# Build report
lines = ['🔔 **"Wallet Monitor" — NEW ACTIVITY!**\n']
for a in new_activities:
    event = a.get("event_type", "?").upper()
    ts = a.get("timestamp", 0)
    dt = datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d %H:%M UTC") if ts else "?"
    token_amt = float(a.get("token_amount", 0))
    quote_amt = float(a.get("quote_amount", 0))
    cost_usd = float(a.get("cost_usd", 0))
    buy_cost = a.get("buy_cost_usd")
    price_usd = float(a.get("price_usd", 0))
    symbol = a.get("token", {}).get("symbol", "?")
    pair_sym = a.get("quote_token", {}).get("symbol", "ETH")
    dex_fee = float(a.get("dex_native", 0))
    tx = a.get("tx_hash", "")[:16]

    total_supply = float(a.get("token", {}).get("total_supply", 1_000_000_000))
    mc = price_usd * total_supply

    line = f"**{event}** {token_amt:,.0f} {symbol}"
    line += f"\n• Pair: {symbol}/{pair_sym}"
    line += f"\n• MC saat transaksi: ${mc:,.0f}"
    line += f"\n• Harga: ${price_usd:.10f}"
    if event == "BUY":
        line += f"\n• Beli: {quote_amt:.4f} {pair_sym} (${cost_usd:,.0f})"
        if buy_cost and float(buy_cost) > 0:
            line += f"\n• Total cost termasuk fee: ${float(buy_cost):,.0f}"
    elif event == "SELL":
        line += f"\n• Jual: {quote_amt:.4f} {pair_sym} (${cost_usd:,.0f})"
    line += f"\n• Dex fee: {dex_fee:.4f} {pair_sym}"
    line += f"\n• Waktu: {dt}"
    line += f"\n• TX: {tx}..."
    lines.append(line)

print("\n\n".join(lines))

# Update state
seen.update(a["tx_hash"] for a in new_activities)
seen_list = list(seen)[-100:]
with open(STATE, "w") as f:
    json.dump({"last_tx_hash": first_tx, "activity_count": new_count, "seen_txs": seen_list}, f)
