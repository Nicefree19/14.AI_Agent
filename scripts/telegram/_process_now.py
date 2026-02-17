#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
One-shot telegram task processor.
Follows the 10-step workflow from CLAUDE.md.
"""
import sys, os, io, json

if sys.stdout.encoding and sys.stdout.encoding.lower().startswith("cp"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
os.chdir(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from scripts.telegram.telegram_bot import (
    check_telegram,
    combine_tasks,
    create_working_lock,
    remove_working_lock,
    reserve_memory_telegram,
    load_memory,
    report_telegram,
    mark_done_telegram,
    get_task_dir,
)
from scripts.telegram.telegram_sender import send_message_sync

# Step 1: Check
pending = check_telegram()
if not pending:
    print("No pending messages.")
    sys.exit(0)

print(f"Found {len(pending)} pending messages")

# Step 2: Combine
combined = combine_tasks(pending)
chat_id = combined["chat_id"]
message_ids = combined["message_ids"]
combined_instruction = combined["combined_instruction"]
timestamps = combined["all_timestamps"]

print(f"Combined {len(message_ids)} messages: {message_ids}")
print(f"Instruction: {combined_instruction[:200]}")

# Output combined for external use
print(json.dumps({
    "chat_id": chat_id,
    "message_ids": message_ids,
    "combined_instruction": combined_instruction,
    "all_timestamps": timestamps,
}, ensure_ascii=False))
