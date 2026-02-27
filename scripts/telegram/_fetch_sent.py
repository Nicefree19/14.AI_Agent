#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Temporary script: fetch sent emails from Outlook for daily report."""
import sys, json, os
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(_ROOT)
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

from datetime import datetime, timedelta
from adapters.outlook_adapter import OutlookAdapter

adapter = OutlookAdapter()
ok = adapter.initialize()
print(f"INIT: {ok}")
if not ok:
    sys.exit(1)

sent_msgs = adapter.fetch(limit=30, folder="sent")
print(f"TOTAL_SENT: {len(sent_msgs)}")

today = datetime.now().date()
yesterday = today - timedelta(days=1)

results = []
for m in sent_msgs:
    if m.timestamp and m.timestamp.date() in (today, yesterday):
        results.append({
            "sender": m.sender,
            "subject": m.subject,
            "ts": str(m.timestamp),
            "body": (m.body or "")[:800],
            "att": m.raw_metadata.get("attachment_names", []),
        })

# Also fetch inbox for today (received items give context)
inbox_msgs = adapter.fetch(limit=30, folder="inbox")
inbox_results = []
for m in inbox_msgs:
    if m.timestamp and m.timestamp.date() in (today, yesterday):
        inbox_results.append({
            "sender": m.sender,
            "subject": m.subject,
            "ts": str(m.timestamp),
            "body": (m.body or "")[:500],
            "att": m.raw_metadata.get("attachment_names", []),
        })

adapter.close()

print(f"SENT_TODAY_YESTERDAY: {len(results)}")
print(f"INBOX_TODAY_YESTERDAY: {len(inbox_results)}")
print("===SENT_JSON===")
print(json.dumps(results, ensure_ascii=False, default=str))
print("===INBOX_JSON===")
print(json.dumps(inbox_results, ensure_ascii=False, default=str))
