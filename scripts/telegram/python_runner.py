#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Python 직행 러너 — 키워드 매칭 스킬을 Claude Code 없이 직접 실행.

p5_autoexecutor.bat에서 quick_check.py 다음, claude_executor.py 이전에 실행된다.
키워드 매칭된 스킬은 순수 Python으로 처리하여 LLM 토큰 소모를 0으로 만든다.

Exit codes:
  0: 스킬 직행 처리 완료 (Claude Code 불필요)
  1: 키워드 미매칭 — Claude Code 필요
  2: 잠금 중 / 메시지 없음 / 기타 스킵
  3: 오류

사용법:
  python python_runner.py
"""

from __future__ import annotations

import os
import sys
import traceback

# ── 프로젝트 루트를 sys.path에 추가 ──
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS_DIR = os.path.dirname(_THIS_DIR)
_PROJECT_ROOT = os.path.dirname(_SCRIPTS_DIR)

os.chdir(_PROJECT_ROOT)

for _p in (_PROJECT_ROOT, _SCRIPTS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ── .env 로드 ──
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_PROJECT_ROOT, ".env"))
except ImportError:
    pass


def _peek_instruction(pending_tasks: list) -> tuple:
    """대기 메시지에서 instruction 텍스트와 파일 정보를 경량 추출.

    combine_tasks를 호출하지 않고 instruction만 빠르게 추출한다.
    여러 메시지가 있으면 모두 합쳐서 하나의 instruction으로 만든다.

    Returns:
        (instruction_text, files_list)
    """
    parts = []
    all_files = []
    for task in pending_tasks:
        instruction = task.get("instruction", "").strip()
        if instruction:
            parts.append(instruction)
        files = task.get("files", [])
        if files:
            all_files.extend(files)

    combined_text = "\n".join(parts)
    return combined_text, all_files or None


def main() -> int:
    """메인 실행 루프.

    흐름:
      1. check_telegram()으로 대기 메시지 확인
      2. instruction에서 is_direct_skill()로 직행 가능 여부 판별
      3. 직행 가능 → run_telegram_task_once(executor) 호출
      4. 직행 불가 → exit(1)로 Claude Code에 위임

    Returns:
        0: 직행 처리 완료
        1: Claude Code 필요 (키워드 미매칭)
        2: 메시지 없음 / 잠금 중
        3: 오류
    """
    try:
        from scripts.telegram.telegram_bot import check_telegram
        from scripts.telegram.telegram_executors import get_executor, is_direct_skill

        # ── Step 1: 대기 메시지 확인 ──
        pending = check_telegram()
        if not pending:
            print("[PYTHON_RUNNER] No pending messages or locked.")
            return 2

        # ── Step 2: instruction 경량 추출 (combine_tasks 없이) ──
        instruction, files = _peek_instruction(pending)
        if not instruction:
            print("[PYTHON_RUNNER] Empty instruction, skipping.")
            return 2

        # ── Step 3: 직행 가능 여부 판별 ──
        if not is_direct_skill(instruction, files=files):
            print(f"[PYTHON_RUNNER] No keyword match → Claude Code needed. "
                  f"(len={len(instruction)}, words={len(instruction.split())})")
            return 1

        # ── Step 4: executor 결정 + 직행 실행 ──
        executor = get_executor(instruction, files=files)
        executor_name = getattr(executor, "__name__", str(executor))
        print(f"[PYTHON_RUNNER] Direct skill matched: {executor_name}")

        # run_telegram_task_once가 내부적으로 check/combine/lock/execute/report/done 전체 처리
        from scripts.telegram.telegram_runner import run_telegram_task_once

        success = run_telegram_task_once(
            executor,
            send_auto_progress=True,
            mark_done_on_error=True,
            pending_tasks=pending,
        )

        if success:
            print(f"[PYTHON_RUNNER] Direct execution completed: {executor_name}")
            return 0
        else:
            print(f"[PYTHON_RUNNER] Execution failed: {executor_name}")
            return 3

    except Exception:
        print("[PYTHON_RUNNER] Error:")
        traceback.print_exc()
        return 3


if __name__ == "__main__":
    sys.exit(main())
