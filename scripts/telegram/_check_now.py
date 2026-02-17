#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""One-shot check: print pending telegram messages as JSON."""
import sys, os, json, io

if sys.stdout.encoding and sys.stdout.encoding.lower().startswith("cp"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
os.chdir(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from scripts.telegram.telegram_bot import check_telegram

result = check_telegram()
print(f"Pending count: {len(result)}")
for r in result:
    print(json.dumps({
        "msg_id": r["message_id"],
        "cls": r.get("classification", "?"),
        "chat_id": r["chat_id"],
        "text": r["instruction"][:120],
        "ts": r["timestamp"],
        "files": len(r.get("files", [])),
    }, ensure_ascii=False))
