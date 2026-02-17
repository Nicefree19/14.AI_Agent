#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
중앙 설정 모듈
==============
프로젝트 전역에서 사용되는 경로/상수를 한 곳에서 관리.
신규 모듈에서 점진적으로 채택 — 기존 하드코딩도 그대로 작동.

의존성: stdlib만 (os, pathlib). 내부 모듈 import 없음 → 순환 import 불가.
"""

from __future__ import annotations

import os
from pathlib import Path

# ═══════════════════════════════════════════════════════════════
#  경로
# ═══════════════════════════════════════════════════════════════

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# 텔레그램 데이터
TELEGRAM_DATA_DIR = PROJECT_ROOT / "telegram_data"
TASKS_DIR = TELEGRAM_DATA_DIR / "tasks"
MESSAGES_FILE = TELEGRAM_DATA_DIR / "telegram_messages.json"
INDEX_FILE = TASKS_DIR / "index.json"
WORKING_LOCK_FILE = TELEGRAM_DATA_DIR / "working.json"
NEW_INSTRUCTIONS_FILE = TELEGRAM_DATA_DIR / "new_instructions.json"
PENDING_REPLY_FILE = TELEGRAM_DATA_DIR / "kakao_pending_reply.json"

# 로그
LOG_DIR = PROJECT_ROOT / "logs"

# ═══════════════════════════════════════════════════════════════
#  타임아웃 / 보존 기간
# ═══════════════════════════════════════════════════════════════

WORKING_LOCK_TIMEOUT = 1800          # 초 (30분)
PENDING_REPLY_TIMEOUT_MIN = 10       # 분
CLEANUP_RETENTION_DAYS = 30          # 일

# 카카오톡 (W4)
KAKAO_CLIPBOARD_WAIT_SEC = 15        # 클립보드 읽기 최대 대기
KAKAO_PS_TIMEOUT_SEC = 5             # PowerShell 명령 타임아웃

# ═══════════════════════════════════════════════════════════════
#  로그 설정
# ═══════════════════════════════════════════════════════════════

LOG_MAX_BYTES = 5 * 1024 * 1024      # 5 MB
LOG_BACKUP_COUNT = 5                 # 최대 5개 백업 → 총 25 MB

# ═══════════════════════════════════════════════════════════════
#  텔레그램
# ═══════════════════════════════════════════════════════════════

TELEGRAM_POLLING_INTERVAL = int(
    os.environ.get("TELEGRAM_POLLING_INTERVAL", "10")
)

# ═══════════════════════════════════════════════════════════════
#  Feature Flags (안전 졸업 제어)
# ═══════════════════════════════════════════════════════════════

FEATURE_FLAGS: dict[str, bool] = {
    "hard_gate_issues": True,        # W1: CRITICAL 이슈 데이터 차단
    "state_machine": True,           # W3: 7단계 메시지 상태 전이
    "error_classification": True,    # W3: 에러 심각도 분류
    "kakao_preflight": True,         # W4: 카카오톡 프리플라이트 체크
    "rag_search": True,              # W5: TF 가중 메모리 검색
    "proactive_alerts": True,        # W6: 건강 모니터링 알림
}


def is_enabled(flag_name: str) -> bool:
    """Feature flag 활성 여부. 미등록 flag → False."""
    return FEATURE_FLAGS.get(flag_name, False)


# ═══════════════════════════════════════════════════════════════
#  에러 심각도 (W3 error_handler.py에서 사용)
# ═══════════════════════════════════════════════════════════════

from enum import Enum  # noqa: E402  (파일 하단 import)


class ErrorSeverity(Enum):
    """에러 심각도 등급."""
    LOW = "low"              # 무시 가능, 로그만
    MEDIUM = "medium"        # 재시도 가능, 사용자 미통보
    HIGH = "high"            # 재시도 필요, 사용자 통보
    CRITICAL = "critical"    # 즉시 중단, 관리자 알림
