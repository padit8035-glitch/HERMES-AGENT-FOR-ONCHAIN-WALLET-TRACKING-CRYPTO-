#!/usr/bin/env python3
"""Bevan cluster wallet alerts — trades + ERC20 transfers, silent when nothing new."""
import json, os, subprocess, sys, time, urllib.request
from datetime import datetime, timezone, timedelta
from config import load_wallets, BASE_DIR

RPC, CHAIN, WALLETS, ADDR2LABEL = load_wallets()
STATE = os.path.join(BASE_DIR, "bevan_alerts_state.json")
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
MAX_ALERTS = 30
WIB = timezone(timedelta(hours=7))

def load_state():
    if os.path.exists(STATE):
        with open(STATE) as f:
            return json.load(f)
    return {"last_block": 0, "seen": []}

def save_state(s):
    s["seen"] = s["seen"][-5000:]
    with open(STATE, "w") as f:
        json.dump(s, f)

def rpc(method, params, tries=2):
    payload = json.dumps({"jsonrpc": "2.0", "method": method, "params": params, "id": 1}).encode()
    for i in range(tries):
        try:
            req = urllib.request.Request(RPC, data=payload, headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode()).get("result")
        except Exception as e:
            if i == tries - 1:
                print(f"⚠️ RPC {method} gagal: {str(e)[:80]}")
                return None
            time.sleep(3)

def human_amt(n):
    n = float(n)
    for div, suf in [(1e9, "B"), (1e6, "M"), (1e3, "K")]:
        if abs(n) >= div:
            return f"{n/div:.2f}{suf}"
    return f"{n:.4f}"

def wib(ts):
    return datetime.fromtimestamp(int(ts), WIB).strftime("%H:%M")

def fmt_trade(label, a):
    sym = a.get("token", {}).get("symbol", "?")
    amt = human_amt(a.get("token_amount", 0))
    usd = float(a.get("cost_usd", 0) or 0)
    cost = float(a.get("buy_cost_usd", 0) or 0)
    side = a.get("event_type", "?").upper()
    if side == "SELL" and cost > 0:
        pnl = usd - cost
        tail = f" | cost ${cost:,.0f} → {'+' if pnl >= 0 else '-'}${abs(pnl):,.0f}"
    else:
        tail = f" | spend ${usd:,.0f}"
    return f"{'🟢' if side=='BUY' else '🔴'} {label} {side} {amt} {sym} @ ${usd:,.0f}{tail} | {wib(a.get('timestamp', 0))} WIB"

def fmt_transfer(label, frm, to, sym, amt):
    fl, tl = ADDR2LABEL.get(frm.lower()), ADDR2LABEL.get(to.lower())
    frm_s = fl if fl else frm[:10] + "…" + frm[-6:]
    to_s = tl if tl else to[:10] + "…" + to[-6:]
    if fl and not tl:
        return f"📤 {label} kirim {human_amt(amt)} {sym} → {to_s}"
    if tl and not fl:
        return f"📥 {label} terima {human_amt(amt)} {sym} dari {frm_s}"
    return f"🔁 {frm_s} ⇄ {to_s}: {human_amt(amt)} {sym}"

def get_trades(addr):
    r = subprocess.run(["gmgn-cli", "portfolio", "activity", "--chain", CHAIN, "--wallet", addr, "--limit", "30"],
                       capture_output=True, text=True, timeout=45)
    if not r.stdout.strip():
        return []
    try:
        return json.loads(r.stdout).get("activities", [])
    except Exception:
        return []

def get_transfers(last_block, latest):
    alerts = []
    step = 50000
    start = max(last_block + 1, latest - 400000)
    for lo in range(start, latest + 1, step):
        hi = min(lo + step - 1, latest)
        res = rpc("eth_getLogs", [{"fromBlock": hex(lo), "toBlock": hex(hi), "topics": [TRANSFER_TOPIC]}])
        if res is None:
            continue
        for log_entry in res:
            topics = log_entry.get("topics", [])
            if len(topics) < 3:
                continue
            frm = "0x" + topics[1][-40:]
            to = "0x" + topics[2][-40:]
            if frm.lower() not in ADDR2LABEL and to.lower() not in ADDR2LABEL:
                continue
            data = log_entry.get("data", "0x")
            try:
                amt = int(data, 16) / 1e18 if len(data) > 2 else 0
            except ValueError:
                amt = 0
            alerts.append((int(log_entry.get("blockNumber", "0x0"), 16), frm, to,
                           "0x" + log_entry.get("address", "")[-40:], amt, log_entry.get("transactionHash", "")))
        time.sleep(1)
    return alerts

def token_sym(addr):
    return "0x" + addr[-6:]

def main():
    state = load_state()
    latest_raw = rpc("eth_blockNumber", [])
    if latest_raw is None:
        return
    latest = int(latest_raw, 16)

    alerts = []
    seen = set(state["seen"])

    # seed first run silently
    if state["last_block"] == 0:
        for label, (addr, trades) in WALLETS.items():
            if trades:
                for a in get_trades(addr):
                    seen.add(a.get("tx_hash", "") + label)
                time.sleep(2)
        state["last_block"] = latest
        state["seen"] = list(seen)
        save_state(state)
        print("✅ Monitor Bevan aktif — baseline dibuat, alert mulai dari pergerakan baru.")
        return

    # trades
    for label, (addr, trades) in WALLETS.items():
        if not trades:
            continue
        for a in get_trades(addr):
            key = (a.get("tx_hash", "") or "") + label
            if key in seen:
                continue
            seen.add(key)
            state["seen"].append(key)
            alerts.append(fmt_trade(label, a))
        time.sleep(2)

    # ERC20 transfers
    for blk, frm, to, tok, amt, txh in sorted(get_transfers(state["last_block"], latest)):
        label = ADDR2LABEL.get(frm.lower()) or ADDR2LABEL.get(to.lower())
        key = f"{txh}{frm[:8]}{to[:8]}"
        if key in seen:
            continue
        seen.add(key)
        state["seen"].append(key)
        alerts.append(fmt_transfer(label, frm, to, token_sym(tok), amt))

    state["last_block"] = latest
    save_state(state)

    if not alerts:
        return
    shown = alerts[:MAX_ALERTS]
    out = f"🔔 *Bevan Watch* ({wib(time.time())} WIB)\n\n" + "\n".join(shown)
    if len(alerts) > MAX_ALERTS:
        out += f"\n\n…+{len(alerts) - MAX_ALERTS} lagi"
    print(out)

def selftest():
    """Self-test with dummy data — no real wallets used."""
    a = {"event_type": "sell", "token": {"symbol": "IF"}, "token_amount": "22231894.9",
         "cost_usd": "239.28", "buy_cost_usd": "138.65", "timestamp": 1788723914}
    s = fmt_trade("test_wallet", a)
    assert "test_wallet SELL 22.23M IF" in s and "+$101" in s, s
    t = fmt_transfer("test_wallet", "0x0000000000000000000000000000000000000001",
                     "0x0000000000000000000000000000000000000002", "0xabc", 500)
    assert "kirim 500.0000" in t, t
    assert human_amt(22231894.9) == "22.23M"
    print("selftest OK")

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        main()
