#!/usr/bin/env python3
"""Read bevan alerts queue and output for delivery. Silent when empty."""
import json, os

QUEUE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bevan_alerts_queue.jsonl")
if not os.path.exists(QUEUE):
    exit(0)

alerts = []
with open(QUEUE) as f:
    for line in f:
        line = line.strip()
        if line:
            try:
                alerts.append(json.loads(line))
            except Exception:
                pass

if not alerts:
    exit(0)

# Clear the queue
os.truncate(QUEUE, 0)

# Output combined
combined = "\n\n".join(a["text"] for a in alerts[:20])
if len(alerts) > 20:
    combined += f"\n\n…+{len(alerts)-20} alerts lagi"
print(combined)
