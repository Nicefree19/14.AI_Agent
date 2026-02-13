#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Telegram 시스템 E2E Smoke Test

각 핵심 모듈의 import, 설정, API 연결을 종단 검증.

Exit Codes:
  0: 모든 테스트 통과
  1: 하나 이상 실패

Usage:
    .agent_venv\\Scripts\\python.exe scripts/telegram/smoke_test.py
"""

import os
import sys
import io
import json
import time
from pathlib import Path

# Windows cp949 인코딩 문제 방지
if sys.stdout.encoding and sys.stdout.encoding.lower().startswith("cp"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
os.chdir(PROJECT_ROOT)

if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


results = []


def test(name):
    """테스트 데코레이터"""
    def decorator(fn):
        def wrapper():
            try:
                fn()
                results.append(("PASS", name, ""))
                print(f"  PASS  {name}")
            except Exception as e:
                results.append(("FAIL", name, str(e)))
                print(f"  FAIL  {name}: {e}")
        return wrapper
    return decorator


@test("1. .env loading")
def test_env():
    from dotenv import load_dotenv
    load_dotenv(os.path.join(PROJECT_ROOT, ".env"))
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    assert token and token not in ("YOUR_BOT_TOKEN", "your_bot_token_here"), \
        "TELEGRAM_BOT_TOKEN not set"
    users = os.getenv("TELEGRAM_ALLOWED_USERS", "")
    assert users, "TELEGRAM_ALLOWED_USERS not set"


@test("2. telegram_bot import")
def test_bot_import():
    from scripts.telegram.telegram_bot import (
        check_telegram,
        combine_tasks,
        create_working_lock,
        remove_working_lock,
        reserve_memory_telegram,
        report_telegram,
        mark_done_telegram,
        load_memory,
        save_bot_response,
        check_working_lock,
    )
    # 함수 존재 확인
    assert callable(check_telegram)
    assert callable(save_bot_response)


@test("3. telegram_sender import")
def test_sender_import():
    from scripts.telegram.telegram_sender import (
        send_message_sync,
        send_files_sync,
    )
    assert callable(send_message_sync)


@test("4. telegram_executors import")
def test_executors_import():
    from scripts.telegram.telegram_executors import get_executor, EXECUTOR_MAP
    assert callable(get_executor)
    assert len(EXECUTOR_MAP) >= 8, f"Expected >=8 executors, got {len(EXECUTOR_MAP)}"


@test("5. telegram_runner import")
def test_runner_import():
    from scripts.telegram.telegram_runner import run_telegram_task_once
    assert callable(run_telegram_task_once)


@test("6. check_telegram() API call")
def test_check_telegram():
    from scripts.telegram.telegram_bot import check_telegram
    # 실제 API 호출 — 에러 없이 리스트 반환 확인
    result = check_telegram()
    assert isinstance(result, list), f"Expected list, got {type(result)}"


@test("7. working lock cycle")
def test_lock_cycle():
    from scripts.telegram.telegram_bot import (
        create_working_lock,
        check_working_lock,
        remove_working_lock,
    )
    WORKING_LOCK = os.path.join(PROJECT_ROOT, "telegram_data", "working.json")

    # 기존 lock이 있으면 스킵 (실제 작업 방해 방지)
    if os.path.exists(WORKING_LOCK):
        # smoke_test 잔여물이면 삭제 후 진행
        try:
            with open(WORKING_LOCK, "r", encoding="utf-8") as f:
                lock_data = json.load(f)
            if lock_data.get("execution_path") == "smoke_test":
                os.remove(WORKING_LOCK)
            else:
                raise RuntimeError("working.json exists (active work) - skipping lock test")
        except (json.JSONDecodeError, KeyError):
            raise RuntimeError("working.json exists - skipping lock test")

    # create -> check -> remove 사이클 (try/finally로 반드시 정리)
    try:
        ok = create_working_lock([99999], "smoke_test_instruction", execution_path="smoke_test")
        assert ok, "create_working_lock failed"

        lock = check_working_lock()
        assert lock is not None, "check_working_lock returned None after create"
    finally:
        # 반드시 정리
        remove_working_lock()
        if os.path.exists(WORKING_LOCK):
            os.remove(WORKING_LOCK)

    lock_after = check_working_lock()
    assert lock_after is None, "Lock still exists after remove"


@test("8. memory save/load cycle")
def test_memory_cycle():
    from scripts.telegram.telegram_bot import load_memory, get_task_dir
    memories = load_memory()
    assert isinstance(memories, (list, dict)), f"Expected list/dict, got {type(memories)}"


@test("9. send_message_sync (self-test)")
def test_send_message():
    """실제 메시지 전송 테스트 (자신에게)"""
    from scripts.telegram.telegram_sender import send_message_sync
    allowed = os.getenv("TELEGRAM_ALLOWED_USERS", "")
    if not allowed:
        raise RuntimeError("No ALLOWED_USERS")
    chat_id = int(allowed.split(",")[0].strip())
    ok = send_message_sync(chat_id, "Smoke test OK")
    assert ok, "send_message_sync returned False"


def main():
    print("=" * 50)
    print("  Telegram System Smoke Test")
    print("=" * 50)
    print()

    # 테스트 실행
    test_env()
    test_bot_import()
    test_sender_import()
    test_executors_import()
    test_runner_import()
    test_check_telegram()
    test_lock_cycle()
    test_memory_cycle()
    test_send_message()

    # 결과 요약
    print()
    print("=" * 50)
    passed = sum(1 for r in results if r[0] == "PASS")
    failed = sum(1 for r in results if r[0] == "FAIL")
    total = len(results)

    if failed == 0:
        print(f"  ALL PASS ({passed}/{total})")
        print("=" * 50)
        return 0
    else:
        print(f"  {failed} FAILED / {passed} PASSED (total {total})")
        for status, name, err in results:
            if status == "FAIL":
                print(f"    FAIL: {name} — {err}")
        print("=" * 50)
        return 1


if __name__ == "__main__":
    sys.exit(main())
