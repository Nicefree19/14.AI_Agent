#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Step 8-10: Report result, mark done, remove lock."""
import sys, os, io

if sys.stdout.encoding and sys.stdout.encoding.lower().startswith("cp"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
os.chdir(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from scripts.telegram.telegram_bot import (
    report_telegram,
    mark_done_telegram,
    remove_working_lock,
)

chat_id = int(sys.argv[1])
message_ids = [int(x) for x in sys.argv[2].split(",")]
timestamps = sys.argv[3].split("|")
instruction = sys.argv[4]
result_text = sys.argv[5]

# Step 8: Report
report_telegram(
    instruction=instruction,
    result_text=result_text,
    chat_id=chat_id,
    timestamp=timestamps,
    message_id=message_ids,
    files=[],
)
print("Report sent")

# Step 9: Mark done
mark_done_telegram(message_ids)
print("Marked done")

# Step 10: Remove lock
remove_working_lock()
print("Lock removed")
print("DONE")
