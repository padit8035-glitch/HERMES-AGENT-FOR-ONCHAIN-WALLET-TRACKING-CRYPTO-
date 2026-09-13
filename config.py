#!/usr/bin/env python3
"""Shared config loader — reads wallets.json next to this file."""
import json, os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WALLETS_FILE = os.path.join(BASE_DIR, "wallets.json")

def load_wallets():
    """Return (rpc, chain, wallets_dict, addr2label).
    wallets_dict: {label: (address, track_trades)}
    addr2label: {address_lower: label}
    """
    with open(WALLETS_FILE) as f:
        cfg = json.load(f)
    rpc = cfg["rpc"]
    chain = cfg["chain"]
    wallets = {}
    for label, entry in cfg["wallets"].items():
        addr = entry["address"]
        track = entry.get("track_trades", False)
        wallets[label] = (addr, track)
    addr2label = {v[0].lower(): k for k, v in wallets.items()}
    return rpc, chain, wallets, addr2label
