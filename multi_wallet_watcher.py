#!/usr/bin/env python3
"""Real-time watcher for multiple wallets — ALL activity, polls periodically."""
import json, subprocess, sys, os, time
from datetime import datetime
from config import load_wallets, BASE_DIR

RPC, CHAIN, WALLETS_RAW, _ = load_wallets()

# Build watcher dict: {address: label} for wallets with track_trades=True
WATCH = {}
for label, (addr, track) in WALLETS_RAW.items():
    if track:
        WATCH[addr] = label

if not WATCH:
    print("No wallets with track_trades=True in wallets.json")
    sys.exit(1)

STATE = os.path.join(BASE_DIR, "revaz_state.json")
POLL_INTERVAL = 3

def load_state():
    if os.path.exists(STATE):
        with open(STATE) as f:
            return json.load(f)
    return {"seen_txs": []}

def save_state(seen_set):
    with open(STATE, "w") as f:
        json.dump({"seen_txs": list(seen_set)[-500:]}, f)

def fetch_activity(wallet):
    r = subprocess.run(
        ["gmgn-cli", "portfolio", "activity", "--chain", CHAIN, "--wallet", wallet, "--limit", "20"],
        capture_output=True, text=True, timeout=30
    )
    if r.returncode != 0:
        return []
    return json.loads(r.stdout).get("activities", [])

def format_alert(wallet_name, activities):
    lines = [f'🔔 **"{wallet_name}" — NEW ACTIVITY!**\n']
    for a in activities:
        event = a.get("event_type", "?")
        ts = a.get("timestamp", 0)
        dt = datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d %H:%M UTC") if ts else "?"
        token_amt = float(a.get("token_amount", 0))
        quote_amt = float(a.get("quote_amount", 0))
        cost_usd = float(a.get("cost_usd", 0))
        buy_cost = a.get("buy_cost_usd")
        price_usd = float(a.get("price_usd", 0))
        symbol = a.get("token", {}).get("symbol", "?")
        token_addr = a.get("token", {}).get("address", "?")[:16]
        pair_sym = a.get("quote_token", {}).get("symbol", "?")
        total_supply = float(a.get("token", {}).get("total_supply", 1_000_000_000))
        mc = price_usd * total_supply if total_supply > 0 else 0
        tx = a.get("tx_hash", "")[:16]
        launchpad = a.get("launchpad", "")

        if event == "buy":
            icon, label = "🟢", "BUY"
        elif event == "sell":
            icon, label = "🔴", "SELL"
        elif event in ("transferIn", "transfer_in"):
            icon, label = "📥", "TRANSFER IN"
        elif event in ("transferOut", "transfer_out"):
            icon, label = "📤", "TRANSFER OUT"
        elif event in ("add", "remove"):
            icon, label = "💧", "LIQUIDITY " + event.upper()
        else:
            icon, label = "⚡", event.upper()

        line = f"{icon} **{label}** {token_amt:,.2f} {symbol}"
        line += f"\n• Token: {symbol} ({token_addr}...)"
        if mc > 0:
            line += f"\n• MC: ${mc:,.0f}"
        if event == "buy":
            line += f"\n• Beli: {cost_usd:,.2f} {pair_sym}"
            if quote_amt and pair_sym not in ("USDG",):
                line += f" ({quote_amt:.6f})"
            if buy_cost and float(buy_cost) > 0:
                line += f"\n• Total cost: ${float(buy_cost):,.2f}"
        elif event == "sell":
            line += f"\n• Jual: {cost_usd:,.2f} {pair_sym}"
            if quote_amt and pair_sym not in ("USDG",):
                line += f" ({quote_amt:.6f})"
        elif "transfer" in event.lower():
            line += f"\n• Amount: {token_amt:,.2f} {symbol}"
            if cost_usd > 0:
                line += f" (${cost_usd:,.2f})"
        if launchpad:
            line += f"\n• Launchpad: {launchpad}"
        line += f"\n• Waktu: {dt}"
        line += f"\n• TX: {tx}..."
        lines.append(line)
    return "\n\n".join(lines)

def send_alert(text):
    max_len = 3800
    if len(text) <= max_len:
        subprocess.run(["hermes", "send", "-t", "telegram", text], capture_output=True, text=True, timeout=15)
    else:
        parts = text.split("\n\n🔔")
        for i, part in enumerate(parts):
            if i > 0:
                part = "🔔" + part
            subprocess.run(["hermes", "send", "-t", "telegram", part], capture_output=True, text=True, timeout=15)
            time.sleep(0.3)

# Init: seed seen set for all wallets
state = load_state()
seen = set(state.get("seen_txs", []))
for wallet in WATCH:
    for a in fetch_activity(wallet):
        seen.add(a["tx_hash"])
save_state(seen)

print(f"Watcher started: {len(WATCH)} wallets, ALL tokens, polling {POLL_INTERVAL}s", flush=True)
for addr, name in WATCH.items():
    print(f"  - {name}: {addr[:14]}...", flush=True)

while True:
    time.sleep(POLL_INTERVAL)
    try:
        for wallet, name in WATCH.items():
            activities = fetch_activity(wallet)
            if not activities:
                continue
            new = [a for a in activities if a["tx_hash"] not in seen]
            if not new:
                continue
            alert = format_alert(name, new)
            send_alert(alert)
            for a in new:
                seen.add(a["tx_hash"])
            save_state(seen)
            print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] ALERT: {name} ({len(new)} txs)", flush=True)
    except Exception as e:
        print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] Error: {e}", flush=True)
        time.sleep(5)
