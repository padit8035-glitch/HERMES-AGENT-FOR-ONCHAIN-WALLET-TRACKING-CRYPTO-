#!/usr/bin/env python3
"""Bevan wallet monitor daemon — polls every ~20s, writes alerts to queue file."""
import json, os, subprocess, sys, time, urllib.request, signal
from datetime import datetime, timezone, timedelta
from config import load_wallets, BASE_DIR

RPC, CHAIN, WALLETS, ADDR2LABEL = load_wallets()
STATE = os.path.join(BASE_DIR, "bevan_daemon_state.json")
QUEUE = os.path.join(BASE_DIR, "bevan_alerts_queue.jsonl")
PID_FILE = os.path.join(BASE_DIR, "bevan_daemon.pid")
NAMES = os.path.join(BASE_DIR, "bevan_names_cache.json")
POLL_INTERVAL = 20
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
WIB = timezone(timedelta(hours=7))

running = True
def _stop(sig, frame):
    global running
    running = False
signal.signal(signal.SIGTERM, _stop)
signal.signal(signal.SIGINT, _stop)

def log(msg):
    ts = datetime.now(WIB).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

def load_state():
    if os.path.exists(STATE):
        with open(STATE) as f:
            return json.load(f)
    return {"last_block": 0, "seen": []}

def save_state(s):
    s["seen"] = s["seen"][-3000:]
    with open(STATE, "w") as f:
        json.dump(s, f)

def rpc(method, params):
    payload = json.dumps({"jsonrpc": "2.0", "method": method, "params": params, "id": 1}).encode()
    try:
        req = urllib.request.Request(RPC, data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode()).get("result")
    except Exception:
        return None

def human_amt(n, is_token=True):
    """Format amount. For tokens: no K/M/B suffixes (confusing), use commas. For USD: K/M/B."""
    n = float(n)
    if not is_token:
        for div, suf in [(1e9, "B"), (1e6, "M"), (1e3, "K")]:
            if abs(n) >= div:
                return f"{n/div:.2f}{suf}"
        return f"{n:,.0f}"
    if abs(n) >= 1e6:
        return f"{n:,.0f}"
    if abs(n) >= 1000:
        return f"{n:,.0f}"
    if abs(n) >= 1:
        return f"{n:,.2f}"
    if abs(n) >= 0.001:
        return f"{n:,.4f}"
    return f"{n:,.6f}"

def wib(ts):
    return datetime.fromtimestamp(int(ts), WIB).strftime("%H:%M")

def queue_alert(text):
    with open(QUEUE, "a") as f:
        f.write(json.dumps({"ts": time.time(), "text": text}) + "\n")

def get_trades(addr, limit=10):
    r = subprocess.run(["gmgn-cli", "portfolio", "activity", "--chain", CHAIN,
                        "--wallet", addr, "--limit", str(limit)],
                       capture_output=True, text=True, timeout=30)
    if not r.stdout.strip():
        return []
    try:
        return json.loads(r.stdout).get("activities", [])
    except Exception:
        return []

def _dexscreener(token_addr):
    """Fetch DexScreener data (cached)."""
    try:
        cache_key = f"/tmp/_ds_{token_addr.lower()}"
        if os.path.exists(cache_key) and (time.time() - os.path.getmtime(cache_key)) < 3600:
            with open(cache_key) as f:
                return json.load(f)
        r = subprocess.run(["curl", "-s", f"https://api.dexscreener.com/latest/dex/tokens/{token_addr}",
            "-H", "User-Agent: Mozilla/5.0"], capture_output=True, text=True, timeout=10)
        pairs = json.loads(r.stdout).get("pairs") or []
        if pairs:
            p = pairs[0]
            data = {"symbol": p.get("baseToken",{}).get("symbol","?"),
                    "name": p.get("baseToken",{}).get("name","?"),
                    "priceUsd": p.get("priceUsd"), "mcap": p.get("marketCap") or p.get("fdv"),
                    "url": p.get("url","")}
            with open(cache_key, "w") as f:
                json.dump(data, f)
            return data
    except:
        pass
    return None

def fmt_transfer(label, frm, to, sym, amt):
    fl = ADDR2LABEL.get(frm.lower())
    tl = ADDR2LABEL.get(to.lower())
    def who(addr, lbl):
        if lbl:
            return lbl
        short = addr[:6] + "..." + addr[-4:]
        name = wallet_name(addr)
        return f"{name} ({short})" if name else short
    a = human_amt(amt)
    if fl and not tl:
        direction, emoji = "KIRIM", "📤"
        wallet, counterparty = fl, who(to, tl)
    elif tl and not fl:
        direction, emoji = "TERIMA", "📥"
        wallet, counterparty = tl, who(frm, fl)
    else:
        direction, emoji = "SWAP", "🔁"
        wallet, counterparty = fl or "?", tl or "?"
    lines = [f"{emoji} {direction} — {wallet}", f"Counterparty: {counterparty}", f"Amount: {a} {sym}"]
    return "\n".join(lines)

def fmt_trade(label, a):
    sym = a.get("token", {}).get("symbol", "?")
    amt = human_amt(a.get("token_amount", 0))
    usd = float(a.get("cost_usd", 0) or 0)
    cost = float(a.get("buy_cost_usd", 0) or 0)
    side = a.get("event_type", "?").upper()
    ts = wib(a.get("timestamp", 0))
    if side == "SELL" and cost > 0:
        pnl = usd - cost
        emoji, action = "📉", "JUAL"
        profit_line = f"Cost: ${cost:,.0f} → PnL: {'+'if pnl>=0 else '-'}${abs(pnl):,.0f}"
    else:
        emoji, action = "📈", "BELI"
        profit_line = f"Spend: ${usd:,.0f}"
    lines = [
        f"{emoji} {action} — {ts} WIB",
        f"Wallet: {label}",
        f"Token: {sym} (Robinhood)",
        f"Amount: {amt} {sym}",
        f"Harga: ${usd:,.0f}",
        profit_line
    ]
    ca = a.get("token", {}).get("address", "")
    if ca:
        ds = _dexscreener(ca)
        if ds and ds.get("mcap"):
            mc = ds["mcap"]
            lines.append(f"Mcap: ${mc/1e6:,.1f}M" if mc >= 1e6 else f"Mcap: ${mc:,.0f}")
    return "\n".join(lines)

_name_cache = None
_lookup_budget = [15]  # ponytail: max GMGN lookups per 20s cycle; leftovers resolved next cycle

def _load_cache():
    global _name_cache
    if _name_cache is None:
        try:
            with open(NAMES) as f:
                _name_cache = json.load(f)
        except Exception:
            _name_cache = {}
    return _name_cache

def _save_cache():
    try:
        with open(NAMES, "w") as f:
            json.dump(_name_cache, f)
    except Exception:
        pass

def _decode_string_or_bytes32(raw):
    """Decode eth_call result: ABI string or bytes32 fallback."""
    if not raw or raw == "0x":
        return None
    try:
        b = bytes.fromhex(raw[2:])
    except Exception:
        return None
    try:
        if len(b) >= 64:
            offset = int.from_bytes(b[0:32], "big")
            length = int.from_bytes(b[offset:offset + 32], "big")
            if 0 < length < 64 and offset + 32 + length <= len(b):
                s = b[offset + 32:offset + 32 + length].decode("utf-8", "ignore").strip("\x00 ")
                if s:
                    return s
    except Exception:
        pass
    s = b.rstrip(b"\x00").decode("utf-8", "ignore").strip()
    return s or None

def token_info(tok):
    """Return {sym, dec} for token contract, cached forever."""
    c = _load_cache()
    k = tok.lower()
    e = c.get("tok:" + k)
    if e is None:
        sym = _decode_string_or_bytes32(rpc("eth_call", [{"to": tok, "data": "0x95d89b41"}, "latest"]))
        raw_dec = rpc("eth_call", [{"to": tok, "data": "0x313ce567"}, "latest"]) or "0x"
        try:
            dec = int(raw_dec, 16)
        except ValueError:
            dec = 18
        if dec <= 0 or dec > 36:
            dec = 18
        e = {"sym": sym or ("0x" + tok[-6:]), "dec": dec}
        c["tok:" + k] = e
        _save_cache()
    return e

def wallet_name(addr):
    """GMGN name/twitter for a wallet, cached forever (None = no name, don't re-query)."""
    c = _load_cache()
    k = addr.lower()
    if k in c:
        return c[k]
    if _lookup_budget[0] <= 0:
        return None
    _lookup_budget[0] -= 1
    name = None
    r = subprocess.run(["gmgn-cli", "portfolio", "stats", "--chain", CHAIN, "--wallet", addr, "--raw"],
                       capture_output=True, text=True, timeout=25)
    if r.stdout.strip():
        try:
            d = json.loads(r.stdout)
            tw = (d.get("common") or {}).get("twitter_username") or ""
            name = ("@" + tw) if tw else (d.get("name") or None)
        except Exception:
            pass
    c[k] = name
    _save_cache()
    return name

def check_trades(seen):
    alerts = []
    for label, (addr, track) in WALLETS.items():
        if not track:
            continue
        trades = get_trades(addr, limit=5)
        time.sleep(1)
        for a in trades:
            key = (a.get("tx_hash", "") or "") + label
            if key in seen:
                continue
            seen.add(key)
            alerts.append(fmt_trade(label, a))
    return alerts

def check_transfers(last_block, latest, seen):
    alerts = []
    if last_block == 0:
        return alerts
    res = rpc("eth_getLogs", [{
        "fromBlock": hex(last_block + 1),
        "toBlock": hex(latest),
        "topics": [TRANSFER_TOPIC]
    }])
    if res is None:
        return alerts
    for log_entry in res:
        topics = log_entry.get("topics", [])
        if len(topics) < 3:
            continue
        frm = "0x" + topics[1][-40:]
        to = "0x" + topics[2][-40:]
        if frm.lower() not in ADDR2LABEL and to.lower() not in ADDR2LABEL:
            continue
        tok = log_entry.get("address", "")
        ti = token_info(tok)
        dec = ti["dec"]
        sym = ti["sym"]
        data = log_entry.get("data", "0x")
        try:
            amt = int(data, 16) / (10 ** dec) if len(data) > 2 else 0
        except ValueError:
            amt = 0
        key = log_entry.get("transactionHash", "") + frm[:8] + to[:8]
        if key in seen:
            continue
        seen.add(key)
        label = ADDR2LABEL.get(frm.lower()) or ADDR2LABEL.get(to.lower())
        alerts.append(fmt_transfer(label, frm, to, sym, amt))
    return alerts

def main():
    global running
    state = load_state()
    seen = set(state["seen"])

    # Write PID
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    latest = rpc("eth_blockNumber", [])
    if latest is None:
        log("⚠️ RPC ga bisa diakses, retry dalam 30s")
        time.sleep(30)
        return
    latest = int(latest, 16)

    if state["last_block"] == 0:
        # First run: seed seen set (trades + transfers)
        log("🚀 First run — seeding baseline...")
        for label, (addr, track) in WALLETS.items():
            if track:
                trades = get_trades(addr, limit=5)
                for a in trades:
                    seen.add((a.get("tx_hash", "") or "") + label)
                time.sleep(1)
        # Also seed transfers so first real check doesn't flood
        res = rpc("eth_getLogs", [{"fromBlock": hex(latest - 50000), "toBlock": hex(latest), "topics": [TRANSFER_TOPIC]}])
        if res:
            for log_entry in res:
                topics = log_entry.get("topics", [])
                if len(topics) >= 3:
                    frm = "0x" + topics[1][-40:]
                    to = "0x" + topics[2][-40:]
                    if frm.lower() in ADDR2LABEL or to.lower() in ADDR2LABEL:
                        seen.add(log_entry.get("transactionHash", "") + frm[:8] + to[:8])
        state["last_block"] = latest
        state["seen"] = list(seen)
        save_state(state)
        log("✅ Baseline done, monitoring mulai")
        return

    alerts = []

    # Check trades (only trading wallets)
    alerts.extend(check_trades(seen))

    # Check ERC20 transfers (trading wallets + funders, skip bot_agg noise)
    res = rpc("eth_getLogs", [{
        "fromBlock": hex(state["last_block"] + 1),
        "toBlock": hex(latest),
        "topics": [TRANSFER_TOPIC]
    }])
    if res:
        for log_entry in res:
            topics = log_entry.get("topics", [])
            if len(topics) < 3:
                continue
            frm = "0x" + topics[1][-40:]
            to = "0x" + topics[2][-40:]
            if frm.lower() not in ADDR2LABEL and to.lower() not in ADDR2LABEL:
                continue
            # Skip bot_agg (too noisy)
            if "bot_agg" in (ADDR2LABEL.get(frm.lower(), "") + ADDR2LABEL.get(to.lower(), "")):
                continue
            data = log_entry.get("data", "0x")
            tok = log_entry.get("address", "")
            ti = token_info(tok)
            dec = ti["dec"]
            sym = ti["sym"]
            # Spam filter: skip unknown tokens (symbol looks like address)
            if not sym or sym.startswith("0x") or len(sym) < 2:
                continue
            try:
                amt = int(data, 16) / (10 ** dec) if len(data) > 2 else 0
            except ValueError:
                amt = 0
            key = log_entry.get("transactionHash", "") + frm[:8] + to[:8]
            if key in seen:
                continue
            seen.add(key)
            label = ADDR2LABEL.get(frm.lower()) or ADDR2LABEL.get(to.lower())
            alerts.append(fmt_transfer(label, frm, to, sym, amt))

    state["last_block"] = latest
    state["seen"] = list(seen)
    save_state(state)

    # Mass airdrop filter: if same sender sent to 3+ wallets, drop all from them
    if alerts:
        sender_counts = {}
        for alert_text in alerts:
            for line in alert_text.split("\n"):
                if "Counterparty:" in line:
                    cp = line.split("Counterparty:")[-1].strip().split("(")[0].strip()
                    sender_counts[cp] = sender_counts.get(cp, 0) + 1
        spam_senders = {s for s, c in sender_counts.items() if c >= 3}
        if spam_senders:
            before = len(alerts)
            alerts = [a for a in alerts if not any(s in a for s in spam_senders)]
            dropped = before - len(alerts)
            if dropped:
                log(f"🚫 Dropped {dropped} spam alerts from {len(spam_senders)} mass airdrop sender(s)")

    if alerts:
        header = f"🔔 *Bevan Watch* ({wib(time.time())} WIB)"
        msg = header + "\n\n" + "\n".join(alerts)
        queue_alert(msg)
        log(f"📢 {len(alerts)} alert queued")
    else:
        log(f"✓ Block {latest} — no new activity")

def cleanup():
    if os.path.exists(PID_FILE):
        os.remove(PID_FILE)

if __name__ == "__main__":
    import atexit
    atexit.register(cleanup)
    log("🔄 Bevan daemon started (poll every 20s)")
    while running:
        try:
            main()
        except Exception as e:
            log(f"❌ Error: {e}")
        if not running:
            break
        time.sleep(POLL_INTERVAL)
    cleanup()
    log("🛑 Daemon stopped")
