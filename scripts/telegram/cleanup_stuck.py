#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Stuck 메시지 정리 스크립트

48시간 이상 pending 상태인 메시지를 안전하게 done 처리.
기본값은 dry_run (실제 변경 없음). --execute 플래그로 실제 실행.

Usage:
    python cleanup_stuck.py              # dry-run (미리보기)
    python cleanup_stuck.py --execute    # 실제 정리
"""

import os
import sys
import json
from datetime import datetime, timedelta
from pathlib import Path

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
MESSAGES_FILE = os.path.join(PROJECT_ROOT, "telegram_data", "telegram_messages.json")
WORKING_LOCK = os.path.join(PROJECT_ROOT, "telegram_data", "working.json")

STALE_HOURS = 48


def find_stuck_messages():
    """48시간 이상 pending 메시지 찾기"""
    if not os.path.exists(MESSAGES_FILE):
        print("telegram_messages.json not found.")
        return []

    with open(MESSAGES_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    cutoff = datetime.now() - timedelta(hours=STALE_HOURS)
    stuck = []

    for msg in data.get("messages", []):
        if msg.get("processed", False):
            continue
        if msg.get("type") == "bot":
            continue

        try:
            ts = datetime.strptime(msg["timestamp"], "%Y-%m-%d %H:%M:%S")
        except (KeyError, ValueError):
            continue

        if ts < cutoff:
            stuck.append(msg)

    return stuck


def cleanup(execute=False):
    """Stuck 메시지 정리"""
    stuck = find_stuck_messages()

    if not stuck:
        print("No stuck messages found.")
        return 0

    print(f"Found {len(stuck)} stuck message(s) (>{STALE_HOURS}h pending):\n")
    for msg in stuck:
        mid = msg.get("message_id", "?")
        ts = msg.get("timestamp", "?")
        text = msg.get("text", "")[:60]
        print(f"  [{mid}] {ts} — {text}")

    if not execute:
        print(f"\nDry run. Use --execute to mark these as done.")
        return len(stuck)

    # 실제 정리
    with open(MESSAGES_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    stuck_ids = {m.get("message_id") for m in stuck}
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for msg in data.get("messages", []):
        if msg.get("message_id") in stuck_ids:
            msg["processed"] = True
            msg["processed_at"] = now
            msg["cleanup_reason"] = f"auto-cleanup: >{STALE_HOURS}h stuck"

    with open(MESSAGES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # working.json도 정리
    if os.path.exists(WORKING_LOCK):
        try:
            os.remove(WORKING_LOCK)
            print("Removed stale working.json")
        except OSError:
            pass

    print(f"\nCleaned up {len(stuck)} stuck message(s).")
    return len(stuck)


if __name__ == "__main__":
    execute = "--execute" in sys.argv
    count = cleanup(execute=execute)
    sys.exit(0 if count == 0 or execute else 1)
