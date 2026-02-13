#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram Task Entry Point

최상위 진입점. telegram_runner.run_telegram_task_once(executor=...) 호출.
직접 실행 또는 스케줄러에서 호출 가능.

Usage:
    python scripts/telegram_task_entry.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# scripts/ 디렉토리를 import path에 추가
_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from telegram.telegram_runner import run_telegram_task_once
from telegram.telegram_executors import get_executor


def main():
    """
    텔레그램 작업 실행 진입점.

    1. 새 메시지 확인 (check_telegram)
    2. 동일 chat_id 메시지 병합 (combine_tasks)
    3. 키워드 기반 executor 선택 (get_executor)
    4. 작업 실행 → 결과 회신 → 완료 처리
    """

    def dispatch_executor(context):
        """combined_instruction에서 키워드 추출 → 적절한 executor 선택 → 실행."""
        instruction = context["combined"]["combined_instruction"]
        executor_func = get_executor(instruction)
        return executor_func(context)

    run_telegram_task_once(
        executor=dispatch_executor,  # 키워드 기반 동적 디스패치
        send_auto_progress=True,     # 자동 진행 상황 보고
        mark_done_on_error=False,    # 에러 시 done 처리하지 않음 (재시도 가능)
    )


if __name__ == "__main__":
    main()
