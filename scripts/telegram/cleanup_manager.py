#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
디스크 클린업 매니저
====================
telegram_data/ 무한 성장 방지.

주요 기능:
  1. cleanup_old_tasks()  — msg_* 폴더 중 N일 초과인 것 삭제
  2. prune_messages()     — telegram_messages.json에서 오래된 처리 완료 메시지 제거
  3. clean_index()        — index.json에서 고아 항목 제거
  4. run_cleanup()        — 전체 오케스트레이터

사용법:
  python -m scripts.telegram.cleanup_manager --days 30
  python -m scripts.telegram.cleanup_manager --dry-run

의존성: stdlib만 (순환 import 방지).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

# ── 경로 (config.py에서 가져오되, 직접 정의도 가능) ──
try:
    from scripts.telegram.config import (
        TELEGRAM_DATA_DIR,
        TASKS_DIR,
        MESSAGES_FILE,
        INDEX_FILE,
        CLEANUP_RETENTION_DAYS,
    )
except ImportError:
    # 스탠드얼론 실행 시 fallback
    _ROOT = Path(__file__).resolve().parent.parent.parent
    TELEGRAM_DATA_DIR = _ROOT / "telegram_data"
    TASKS_DIR = TELEGRAM_DATA_DIR / "tasks"
    MESSAGES_FILE = TELEGRAM_DATA_DIR / "telegram_messages.json"
    INDEX_FILE = TASKS_DIR / "index.json"
    CLEANUP_RETENTION_DAYS = 30

# ── 로거 (가능하면 중앙 로거, 아니면 print) ──
try:
    from scripts.telegram.logger import get_logger
    log = get_logger(__name__)
except ImportError:
    import logging
    log = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO)

# ── 날짜 파싱 패턴 ──
_DATE_RE = re.compile(r"\[시간\]\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})")


def _atomic_json_write(filepath: Path, data) -> None:
    """원자적 JSON 쓰기 (인라인 — telegram_bot.py import 방지)."""
    tmp = filepath.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(filepath)


# ═══════════════════════════════════════════════════════════════
#  1. 오래된 작업 폴더 삭제
# ═══════════════════════════════════════════════════════════════

def cleanup_old_tasks(days: int = CLEANUP_RETENTION_DAYS, dry_run: bool = False) -> int:
    """msg_* 폴더 중 task_info.txt의 [시간]이 N일 초과인 것 삭제.

    Returns:
        삭제된 폴더 수.
    """
    cutoff = datetime.now() - timedelta(days=days)
    deleted = 0

    if not TASKS_DIR.exists():
        return 0

    for folder in sorted(TASKS_DIR.iterdir()):
        if not folder.is_dir() or not folder.name.startswith("msg_"):
            continue

        task_info = folder / "task_info.txt"
        if not task_info.exists():
            # task_info 없는 고아 폴더도 삭제 대상
            if dry_run:
                log.info(f"[DRY-RUN] 삭제 예정 (task_info 없음): {folder.name}")
            else:
                try:
                    shutil.rmtree(folder)
                    log.info(f"삭제: {folder.name} (task_info 없음)")
                except Exception as exc:
                    log.warning(f"삭제 실패: {folder.name}: {exc}")
            deleted += 1
            continue

        # [시간] 파싱
        try:
            text = task_info.read_text(encoding="utf-8", errors="replace")
            match = _DATE_RE.search(text)
            if not match:
                continue  # 날짜 파싱 불가 → 건드리지 않음
            task_time = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S")
        except Exception:
            continue

        if task_time < cutoff:
            if dry_run:
                log.info(f"[DRY-RUN] 삭제 예정: {folder.name} ({task_time.date()})")
            else:
                try:
                    shutil.rmtree(folder)
                    log.info(f"삭제: {folder.name} ({task_time.date()})")
                except Exception as exc:
                    log.warning(f"삭제 실패: {folder.name}: {exc}")
            deleted += 1

    return deleted


# ═══════════════════════════════════════════════════════════════
#  2. 오래된 처리 완료 메시지 정리
# ═══════════════════════════════════════════════════════════════

def prune_messages(days: int = CLEANUP_RETENTION_DAYS, dry_run: bool = False) -> int:
    """telegram_messages.json에서 processed=True + N일 초과 메시지 제거.

    미처리(processed=False) 메시지는 절대 삭제하지 않음.

    Returns:
        제거된 메시지 수.
    """
    if not MESSAGES_FILE.exists():
        return 0

    try:
        with open(MESSAGES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        log.warning(f"telegram_messages.json 읽기 실패: {exc}")
        return 0

    messages = data.get("messages", [])
    cutoff = datetime.now() - timedelta(days=days)
    keep = []
    pruned = 0

    for msg in messages:
        # 미처리 메시지 → 보존
        if not msg.get("processed", False):
            keep.append(msg)
            continue

        # 날짜 확인
        msg_date_str = msg.get("date", "")
        try:
            msg_date = datetime.fromisoformat(msg_date_str)
        except (ValueError, TypeError):
            keep.append(msg)  # 파싱 불가 → 보존
            continue

        if msg_date < cutoff:
            pruned += 1
            if dry_run:
                log.info(f"[DRY-RUN] 메시지 제거 예정: ID {msg.get('message_id', '?')} ({msg_date.date()})")
        else:
            keep.append(msg)

    if pruned > 0 and not dry_run:
        data["messages"] = keep
        _atomic_json_write(MESSAGES_FILE, data)
        log.info(f"메시지 정리: {pruned}개 제거, {len(keep)}개 보존")

    return pruned


# ═══════════════════════════════════════════════════════════════
#  3. 인덱스 고아 항목 정리
# ═══════════════════════════════════════════════════════════════

def clean_index(dry_run: bool = False) -> int:
    """index.json에서 폴더가 없는 고아 항목 제거.

    Returns:
        제거된 항목 수.
    """
    if not INDEX_FILE.exists():
        return 0

    try:
        with open(INDEX_FILE, "r", encoding="utf-8") as f:
            index_data = json.load(f)
    except Exception as exc:
        log.warning(f"index.json 읽기 실패: {exc}")
        return 0

    tasks = index_data.get("tasks", [])
    keep = []
    orphaned = 0

    for entry in tasks:
        task_dir = entry.get("task_dir", "")
        # task_dir는 "tasks/msg_X" 형식
        full_path = TELEGRAM_DATA_DIR / task_dir
        if full_path.is_dir():
            keep.append(entry)
        else:
            orphaned += 1
            if dry_run:
                log.info(f"[DRY-RUN] 인덱스 고아 제거 예정: {task_dir}")

    if orphaned > 0 and not dry_run:
        index_data["tasks"] = keep
        _atomic_json_write(INDEX_FILE, index_data)
        log.info(f"인덱스 정리: {orphaned}개 고아 항목 제거")

    return orphaned


# ═══════════════════════════════════════════════════════════════
#  4. 전체 오케스트레이터
# ═══════════════════════════════════════════════════════════════

def run_cleanup(days: int = CLEANUP_RETENTION_DAYS, dry_run: bool = False) -> dict:
    """전체 정리 실행. 결과 요약 반환."""
    mode = "[DRY-RUN] " if dry_run else ""
    log.info(f"{mode}클린업 시작 (보존 기간: {days}일)")

    result = {
        "tasks_deleted": cleanup_old_tasks(days=days, dry_run=dry_run),
        "messages_pruned": prune_messages(days=days, dry_run=dry_run),
        "index_orphans": clean_index(dry_run=dry_run),
    }

    total = sum(result.values())
    log.info(
        f"{mode}클린업 완료: "
        f"폴더 {result['tasks_deleted']}개, "
        f"메시지 {result['messages_pruned']}개, "
        f"인덱스 {result['index_orphans']}개 "
        f"(총 {total}개 항목)"
    )
    return result


# ═══════════════════════════════════════════════════════════════
#  CLI 진입점
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="텔레그램 봇 디스크 클린업",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--days", type=int, default=CLEANUP_RETENTION_DAYS,
        help=f"보존 기간 (기본: {CLEANUP_RETENTION_DAYS}일)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="삭제하지 않고 대상만 표시",
    )
    args = parser.parse_args()

    result = run_cleanup(days=args.days, dry_run=args.dry_run)

    # 종료 코드: 0=정상, 1=오류(위에서 except 처리)
    sys.exit(0)


if __name__ == "__main__":
    main()
