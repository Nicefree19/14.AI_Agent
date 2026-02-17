#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fetch sent emails by 이동혁 from wider date range + more inbox detail."""
import sys, json, os
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(_ROOT)
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

from datetime import datetime, timedelta
from adapters.outlook_adapter import OutlookAdapter

adapter = OutlookAdapter()
ok = adapter.initialize()
if not ok:
    print("INIT_FAILED")
    sys.exit(1)

# Fetch more sent emails (50) to find today's
sent_msgs = adapter.fetch(limit=50, folder="sent")
today = datetime.now().date()
yesterday = today - timedelta(days=1)

# Filter for 이동혁 sent emails (today/yesterday/wider)
sent_results = []
for m in sent_msgs:
    sender = m.sender or ""
    if "이동혁" in sender or "dhlee" in sender.lower():
        sent_results.append({
            "subject": m.subject,
            "ts": str(m.timestamp),
            "body": (m.body or "")[:1200],
            "att": m.raw_metadata.get("attachment_names", []),
            "date": str(m.timestamp.date()) if m.timestamp else "",
        })

# Also get ALL sent emails from any sender today/yesterday
all_sent = []
for m in sent_msgs:
    if m.timestamp and m.timestamp.date() in (today, yesterday):
        all_sent.append({
            "sender": m.sender,
            "subject": m.subject,
            "ts": str(m.timestamp),
            "body": (m.body or "")[:400],
        })

adapter.close()

print(f"DHLee_SENT: {len(sent_results)}")
print(f"ALL_SENT_TODAY: {len(all_sent)}")
print("===DHLEE_JSON===")
print(json.dumps(sent_results[:10], ensure_ascii=False))
print("===ALL_SENT_JSON===")
print(json.dumps(all_sent[:10], ensure_ascii=False))
