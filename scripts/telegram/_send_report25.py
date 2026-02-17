#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Send report for msg_25 and finalize."""
import sys, os
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(_ROOT)
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

from scripts.telegram.telegram_bot import report_telegram, mark_done_telegram, remove_working_lock

report_path = os.path.join(_ROOT, "telegram_data", "tasks", "msg_25", "daily_report_20260213.txt")

# Read report
with open(report_path, "r", encoding="utf-8") as f:
    report_text = f.read()

# Send report
report_telegram(
    instruction="최근 내가 보낸 메일분석후 이동혁소장의 일일 업무보고서 작성해줘",
    result_text=report_text,
    chat_id=8468392331,
    timestamp=["2026-02-13 12:33:20"],
    message_id=[25],
    files=[report_path],
)
print("REPORT_SENT")

# Mark done
mark_done_telegram([25])
print("MARKED_DONE")

# Remove lock
remove_working_lock()
print("LOCK_REMOVED")
