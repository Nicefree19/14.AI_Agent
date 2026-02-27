#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Post-task wait loop: ask for more tasks, poll 3 minutes, exit."""
import sys, os, io, time

if sys.stdout.encoding and sys.stdout.encoding.lower().startswith("cp"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(_ROOT)
sys.path.insert(0, _ROOT)

from scripts.telegram.telegram_sender import send_message_sync
from scripts.telegram.telegram_bot import check_telegram

CHAT_ID = 8468392331
POLL_INTERVAL = 30  # seconds between checks
POLL_DURATION = 180  # 3 minutes total

# Send follow-up message
send_message_sync(CHAT_ID, "✅ 모든 작업 완료! 추가 지시사항이 있으시면 보내주세요. (3분간 대기 후 종료)")
print("Follow-up sent. Starting 3-minute poll loop...")

elapsed = 0
cycle = 0
while elapsed < POLL_DURATION:
    cycle += 1
    time.sleep(POLL_INTERVAL)
    elapsed += POLL_INTERVAL

    print(f"[{elapsed}s / {POLL_DURATION}s] Checking for new messages (cycle {cycle})...")
    try:
        pending = check_telegram()
        if pending:
            print(f"NEW_MESSAGES_FOUND: {len(pending)}")
            for t in pending:
                print(f"  msg_id={t.get('message_id')}: {t.get('instruction','')[:80]}")
            sys.exit(1)  # Signal: new messages found
        else:
            print("  No new messages.")
    except Exception as e:
        print(f"  Check error: {e}")

print("3 minutes elapsed. No new messages. Exiting.")
sys.exit(0)
