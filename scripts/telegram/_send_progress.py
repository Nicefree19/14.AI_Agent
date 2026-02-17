#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Send a progress message to telegram."""
import sys, os, io

if sys.stdout.encoding and sys.stdout.encoding.lower().startswith("cp"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
os.chdir(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from scripts.telegram.telegram_sender import send_message_sync

chat_id = int(sys.argv[1])
message = sys.argv[2]
result = send_message_sync(chat_id, message)
print(f"Sent: {result}")
