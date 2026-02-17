#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
다른 프로젝트의 업무관리 모듈에서 재사용하기 위한 텔레그램 작업 러너.

핵심 아이디어:
- 텔레그램 작업의 공통 흐름(check/combine/lock/memory/report/done)을 이 파일이 처리
- 실제 업무 로직은 executor 콜백으로 분리

원본: /mnt/d/00.Work_AI_Tool/16.mybot_ver2/telegram_agent_runner.py
변경: 상대 임포트, chat_id 그룹핑 적용
"""

from __future__ import annotations

import os
import traceback
from typing import Any, Callable, Dict, List

from .telegram_bot import (
    check_telegram,
    combine_tasks,
    create_working_lock,
    remove_working_lock,
    reserve_memory_telegram,
    report_telegram,
    mark_done_telegram,
    load_memory,
    load_memory_for_task,
    get_task_dir,
)
from .telegram_sender import send_message_sync


TaskContext = Dict[str, Any]
ExecutorResult = Dict[str, Any]
TaskExecutor = Callable[[TaskContext], ExecutorResult]


def _start_message(message_count: int) -> str:
    if message_count > 1:
        return f"✅ 작업을 시작했습니다! (총 {message_count}개 요청 합산 처리)"
    return "✅ 작업을 시작했습니다!"


def run_telegram_task_once(
    executor: TaskExecutor,
    *,
    send_auto_progress: bool = True,
    mark_done_on_error: bool = False,
    pending_tasks: list | None = None,
) -> bool:
    """
    대기 중인 텔레그램 작업을 1회 처리한다.

    Args:
        executor:
            실제 업무를 수행하는 콜백.
            입력: context(dict)
            출력: {"result_text": str, "files": list[str]} 형식 dict
        send_auto_progress:
            True면 공통 단계에서 기본 진행 메시지를 전송한다.
        mark_done_on_error:
            True면 오류가 발생해도 report + done 처리한다.
            False면 오류 메시지만 보내고 미처리 상태로 남겨 다음 주기에 재시도한다.

    Returns:
        bool:
            - True: 작업 처리 완료
            - False: 대기 작업 없음, 잠금 실패, 혹은 실행 오류
    """
    pending = pending_tasks if pending_tasks is not None else check_telegram()
    if not pending:
        return False

    combined = combine_tasks(pending)
    if not combined:
        return False

    chat_id = combined["chat_id"]
    message_ids = combined["message_ids"]
    combined_instruction = combined["combined_instruction"]
    timestamps = combined["all_timestamps"]

    if not create_working_lock(message_ids, combined_instruction, execution_path="telegram_runner"):
        return False

    send_message_sync(chat_id, _start_message(len(message_ids)))

    previous_cwd = os.getcwd()

    try:
        reserve_memory_telegram(
            combined_instruction,
            chat_id,
            timestamps,
            message_ids,
        )

        memories = load_memory_for_task(combined_instruction, limit=5)
        task_dir = get_task_dir(message_ids[0])
        os.chdir(task_dir)

        def send_progress(text: str) -> None:
            send_message_sync(chat_id, text)

        if send_auto_progress:
            send_progress("📊 메모리 조사 및 작업 환경 준비 완료")

        context: TaskContext = {
            "combined": combined,
            "memories": memories,
            "task_dir": task_dir,
            "send_progress": send_progress,
        }

        result = executor(context)
        if not isinstance(result, dict):
            raise TypeError("executor는 dict 결과를 반환해야 합니다.")

        result_text = str(result.get("result_text", "작업 완료"))
        files = result.get("files", [])
        if files is None:
            files = []
        if not isinstance(files, list):
            raise TypeError("executor 반환값의 files는 list여야 합니다.")

        if send_auto_progress:
            send_progress("📊 결과 정리 및 전송 중...")

        send_ok = report_telegram(
            combined_instruction,
            result_text,
            chat_id,
            timestamps,
            message_ids,
            files=files,
        )
        if send_ok:
            mark_done_telegram(message_ids)
        else:
            from .telegram_sender import get_last_send_error
            err = get_last_send_error() or "unknown"
            print(f"⚠️ 전송 실패 ({err}), mark_done 생략 — 다음 주기에 재시도")
        return True

    except Exception as exc:  # noqa: BLE001
        # 에러 분류 통합
        try:
            from .error_handler import classify_error, handle_error
            severity, category = classify_error(exc)
            handle_error(exc, severity, category, context={
                "message_ids": str(message_ids),
                "instruction": combined_instruction[:100],
            })
        except Exception:
            pass  # 에러 분류 자체 실패가 본 흐름을 방해하지 않음

        short_error = f"{type(exc).__name__}: {exc}"
        send_message_sync(
            chat_id,
            "❌ 작업 중 오류가 발생했습니다.\n"
            f"- 오류: `{short_error}`\n"
            "다음 주기에 재시도할 수 있도록 상태를 정리합니다.",
        )

        if mark_done_on_error:
            report_telegram(
                combined_instruction,
                "실패로 종료됨\n\n" + traceback.format_exc()[-1000:],
                chat_id,
                timestamps,
                message_ids,
                files=[],
            )
            mark_done_telegram(message_ids)

        return False

    finally:
        os.chdir(previous_cwd)
        remove_working_lock()


if __name__ == "__main__":
    def _example_executor(context: TaskContext) -> ExecutorResult:
        send_progress = context["send_progress"]
        send_progress("📊 예제 executor 실행 중...")

        task_dir = context["task_dir"]
        output_file = os.path.join(task_dir, "result.txt")
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("example result\n")

        return {
            "result_text": "예제 작업 완료",
            "files": [output_file],
        }

    processed = run_telegram_task_once(_example_executor, send_auto_progress=True)
    if not processed:
        print("처리할 메시지가 없거나 실행에 실패했습니다.")
