#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Quick check for new pending Telegram messages."""
import sys, json, os
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(_ROOT)
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

from scripts.telegram.telegram_bot import check_telegram

pending = check_telegram()
if not pending:
    print("NO_PENDING")
else:
    print(json.dumps(pending, ensure_ascii=False, default=str))
