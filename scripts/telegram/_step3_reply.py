#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Step 3: Send immediate reply + Step 4: Create working lock + Step 5: Reserve memory."""
import sys, os, io

if sys.stdout.encoding and sys.stdout.encoding.lower().startswith("cp"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
os.chdir(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from scripts.telegram.telegram_bot import (
    check_telegram,
    combine_tasks,
    create_working_lock,
    reserve_memory_telegram,
    load_memory,
    get_task_dir,
)
from scripts.telegram.telegram_sender import send_message_sync

# Step 1-2: Check + Combine
pending = check_telegram()
if not pending:
    print("NO_PENDING")
    sys.exit(0)

combined = combine_tasks(pending)
chat_id = combined["chat_id"]
message_ids = combined["message_ids"]
combined_instruction = combined["combined_instruction"]
timestamps = combined["all_timestamps"]

# Step 3: Immediate reply
msg = f"✅ 작업을 시작했습니다! (총 {len(message_ids)}개 요청 합산 처리)\n\n"
msg += "📋 요청 내역:\n"
for i, p in enumerate(pending, 1):
    msg += f"  {i}. {p['instruction'][:50]}\n"
msg += "\n⏳ 처리 중... 잠시만 기다려주세요."

result = send_message_sync(chat_id, msg)
print(f"Reply sent: {result}")

# Step 4: Create working lock
ok = create_working_lock(message_ids, combined_instruction, execution_path="claude_session")
print(f"Lock created: {ok}")
if not ok:
    print("LOCK_FAILED")
    sys.exit(2)

# Step 5: Reserve memory
reserve_memory_telegram(combined_instruction, chat_id, timestamps, message_ids)
print("Memory reserved")

# Step 6: Load memory
memories = load_memory()
print(f"Memories loaded: {len(memories)} entries")

# Output task_dir for the first message
task_dir = get_task_dir(message_ids[0])
print(f"Task dir: {task_dir}")
print("READY")
