#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
건강 모니터링 모듈 (W6)
========================
작업 완료 후 시스템 상태를 자동 점검하고 이상 시 알림.

6개 점검:
  1. 디스크 여유 공간
  2. 로그 파일 크기
  3. 스탈 작업 잠금
  4. 미처리 메시지 큐
  5. 실패 상태 메시지
  6. 인덱스 무결성

의존성: stdlib + 내부 모듈만. 읽기 전용 (부작용 없음).
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Any

from .config import (
    TELEGRAM_DATA_DIR,
    TASKS_DIR,
    MESSAGES_FILE,
    INDEX_FILE,
    WORKING_LOCK_FILE,
    WORKING_LOCK_TIMEOUT,
    LOG_DIR,
    LOG_MAX_BYTES,
    LOG_BACKUP_COUNT,
)
from .logger import get_logger

log = get_logger(__name__)

# ═══════════════════════════════════════════════════════════════
#  임계값
# ═══════════════════════════════════════════════════════════════

DISK_WARN_MB = 500           # 디스크 여유 < 500MB → warn
DISK_CRITICAL_MB = 100       # 디스크 여유 < 100MB → critical
LOG_WARN_MB = 20             # 로그 총 용량 > 20MB → warn
PENDING_WARN_COUNT = 10      # 미처리 메시지 > 10개 → warn

# ═══════════════════════════════════════════════════════════════
#  스로틀링
# ═══════════════════════════════════════════════════════════════

_ALERT_INTERVAL_SEC = 3600   # 최소 알림 간격 (1시간)
_last_alert_time: float = 0.0


def should_send_alert() -> bool:
    """1시간 내 알림이 이미 전송되었으면 False."""
    now = time.time()
    if now - _last_alert_time < _ALERT_INTERVAL_SEC:
        return False
    return True


def mark_alert_sent() -> None:
    """알림 전송 시각 기록."""
    global _last_alert_time
    _last_alert_time = time.time()


# ═══════════════════════════════════════════════════════════════
#  개별 점검 함수
# ═══════════════════════════════════════════════════════════════

def _check_disk_space() -> dict:
    """프로젝트 드라이브 여유 공간 확인."""
    usage = shutil.disk_usage(str(TELEGRAM_DATA_DIR))
    free_mb = usage.free / (1024 * 1024)

    if free_mb < DISK_CRITICAL_MB:
        status = "critical"
    elif free_mb < DISK_WARN_MB:
        status = "warn"
    else:
        status = "ok"

    return {
        "name": "disk_space",
        "status": status,
        "message": f"여유 {free_mb:.0f}MB",
        "value": free_mb,
    }


def _check_log_size() -> dict:
    """agent.log + 백업 파일 총 용량 확인."""
    total_bytes = 0
    log_file = LOG_DIR / "agent.log"

    if log_file.exists():
        total_bytes += log_file.stat().st_size

    # 백업 파일: agent.log.1, agent.log.2, ...
    for i in range(1, LOG_BACKUP_COUNT + 1):
        backup = LOG_DIR / f"agent.log.{i}"
        if backup.exists():
            total_bytes += backup.stat().st_size

    total_mb = total_bytes / (1024 * 1024)

    if total_mb > LOG_WARN_MB:
        status = "warn"
    else:
        status = "ok"

    return {
        "name": "log_size",
        "status": status,
        "message": f"로그 총 {total_mb:.1f}MB",
        "value": total_mb,
    }


def _check_stale_locks() -> dict:
    """working.json 스탈 감지. telegram_bot.check_working_lock() 재사용."""
    from .telegram_bot import check_working_lock  # 지연 import (순환 방지)

    lock = check_working_lock()
    if lock is None:
        return {
            "name": "stale_locks",
            "status": "ok",
            "message": "활성 잠금 없음",
            "value": None,
        }

    if lock.get("stale"):
        msg_id = lock.get("message_id", "?")
        return {
            "name": "stale_locks",
            "status": "critical",
            "message": f"스탈 작업 감지 (msg {msg_id})",
            "value": lock,
        }

    return {
        "name": "stale_locks",
        "status": "ok",
        "message": "정상 작업 진행 중",
        "value": lock,
    }


def _check_pending_messages() -> dict:
    """미처리 메시지 큐 크기 확인."""
    from .telegram_bot import load_telegram_messages  # 지연 import

    data = load_telegram_messages()
    messages = data.get("messages", [])
    pending = [m for m in messages if not m.get("processed", False)]
    count = len(pending)

    if count > PENDING_WARN_COUNT:
        status = "warn"
    else:
        status = "ok"

    return {
        "name": "pending_messages",
        "status": status,
        "message": f"미처리 {count}건",
        "value": count,
    }


def _check_failed_states() -> dict:
    """FAILED 상태 메시지 존재 확인."""
    from .telegram_bot import load_telegram_messages  # 지연 import

    data = load_telegram_messages()
    messages = data.get("messages", [])
    failed = [m for m in messages if m.get("state") == "failed"]
    count = len(failed)

    if count > 0:
        status = "warn"
    else:
        status = "ok"

    return {
        "name": "failed_states",
        "status": status,
        "message": f"실패 {count}건",
        "value": count,
    }


def _check_index_integrity() -> dict:
    """고아 인덱스 항목 존재 확인. cleanup_manager.clean_index(dry_run=True) 재사용."""
    from .cleanup_manager import clean_index  # 지연 import

    orphan_count = clean_index(dry_run=True)

    if orphan_count > 0:
        status = "warn"
    else:
        status = "ok"

    return {
        "name": "index_integrity",
        "status": status,
        "message": f"고아 항목 {orphan_count}건",
        "value": orphan_count,
    }


# ═══════════════════════════════════════════════════════════════
#  오케스트레이터
# ═══════════════════════════════════════════════════════════════

def run_health_check() -> dict:
    """6개 시스템 점검 실행. 항상 안전 (예외 시 해당 점검만 skip)."""
    checks: list[dict] = []

    for check_fn in [
        _check_disk_space,
        _check_log_size,
        _check_stale_locks,
        _check_pending_messages,
        _check_failed_states,
        _check_index_integrity,
    ]:
        try:
            checks.append(check_fn())
        except Exception as exc:
            checks.append({
                "name": check_fn.__name__.replace("_check_", ""),
                "status": "warn",
                "message": f"점검 실행 실패: {exc}",
                "value": None,
            })

    healthy = all(c["status"] == "ok" for c in checks)
    issues = [c for c in checks if c["status"] != "ok"]

    if healthy:
        summary = "시스템 정상"
    else:
        summary = f"{len(issues)}건 이상 감지"

    return {"healthy": healthy, "checks": checks, "summary": summary}


# ═══════════════════════════════════════════════════════════════
#  알림 포맷
# ═══════════════════════════════════════════════════════════════

_STATUS_ICON = {"ok": "✅", "warn": "⚠️", "critical": "🚨"}


def format_alert_message(report: dict) -> str:
    """건강 점검 결과를 텔레그램 알림 메시지로 포맷."""
    lines = ["🏥 시스템 건강 점검 결과", ""]

    for check in report.get("checks", []):
        status = check.get("status", "ok")
        icon = _STATUS_ICON.get(status, "❓")
        name = check.get("name", "unknown")
        message = check.get("message", "")
        lines.append(f"{icon} {name}: {message}")

    lines.append("")
    lines.append(f"요약: {report.get('summary', '알 수 없음')}")

    return "\n".join(lines)
