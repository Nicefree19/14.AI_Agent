#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
빠른 텔레그램 메시지 확인 (Claude Code 실행 전)

Exit Codes:
  0: 새 메시지 없음 (즉시 종료)
  1: 새 메시지 있음 (Claude Code 실행 필요)
  2: 다른 작업 진행 중 (working.json 활성 잠금)
  3: 오류 발생 (다음 주기에 재시도)
"""

import os
import sys

# 프로젝트 루트로 이동 (scripts/telegram/ → 프로젝트 루트)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
os.chdir(PROJECT_ROOT)

# 프로젝트 루트를 sys.path에 추가하여 scripts 패키지 임포트 가능
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# ── .env 필수 변수 검증 ──
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(PROJECT_ROOT, ".env"))
except ImportError:
    pass  # dotenv 없어도 os.environ에서 읽기 시도

_bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
_allowed = os.getenv("TELEGRAM_ALLOWED_USERS", "")

if not _bot_token or _bot_token in ("YOUR_BOT_TOKEN", "your_bot_token_here"):
    print("Error: TELEGRAM_BOT_TOKEN not set in .env")
    sys.exit(3)

if not _allowed:
    print("Error: TELEGRAM_ALLOWED_USERS not set in .env")
    sys.exit(3)

# ── 메시지 확인 ──
from scripts.telegram.telegram_bot import check_telegram, check_working_lock

try:
    # 잠금 상태 먼저 확인 (check_telegram보다 빠름)
    lock = check_working_lock()
    if lock and not lock.get("stale"):
        print(f"Locked: {lock.get('instruction_summary', '?')}")
        sys.exit(2)

    # 새 메시지 확인 (스탈 잠금은 check_telegram 내부에서 처리)
    pending = check_telegram()
    if not pending:
        sys.exit(0)

    # 새 메시지 있음
    print(f"New messages: {len(pending)}")
    sys.exit(1)

except Exception as e:
    print(f"Error: {e}")
    sys.exit(3)
