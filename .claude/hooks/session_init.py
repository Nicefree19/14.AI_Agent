#!/usr/bin/env python
"""
session_init.py - 세션 초기화 훅
이벤트: SessionStart (startup|resume|compact)

- startup: 세션 상태 초기화 + 4대 시스템 리마인더
- resume: 기존 상태 유지 + 상태 요약 출력
- compact: 컨텍스트 압축 후 핵심 상태 재주입
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hook_utils import (
    read_stdin_json,
    load_session_state,
    init_session_state,
)

SYSTEM_REMINDER = (
    "4대 시스템 활성화: "
    "[1]작업기억(계획→체크리스트→맥락노트) | "
    "[2]자동매뉴얼(guide_loader) | "
    "[3]품질게이트(quality_gate) | "
    "[4]리뷰강제(stop_guardian)"
)


def main():
    data = read_stdin_json()
    session_type = data.get("type", "startup")

    if session_type == "startup":
        # 새 세션: 상태 초기화
        init_session_state()
        print(f"[세션 시작] {SYSTEM_REMINDER}")

    elif session_type == "resume":
        # 세션 재개: 기존 상태 로드 + 요약
        state = load_session_state()
        total = state.get("total_modifications", 0)
        fails = state.get("qa_fail_count", 0)
        if total > 0:
            print(
                f"[세션 재개] 이전 상태 복원: "
                f"수정 파일 {total}개, QA FAIL {fails}개\n"
                f"{SYSTEM_REMINDER}"
            )
        else:
            print(f"[세션 재개] {SYSTEM_REMINDER}")

    elif session_type == "compact":
        # 컨텍스트 압축: 핵심 상태 재주입
        state = load_session_state()
        total = state.get("total_modifications", 0)
        fails = state.get("qa_fail_count", 0)
        walkthrough = state.get("walkthrough_detected", False)

        mod_files = list(state.get("modified_files", {}).keys())
        files_summary = ", ".join(mod_files[:5])
        if len(mod_files) > 5:
            files_summary += f" 외 {len(mod_files) - 5}개"

        print(
            f"[컨텍스트 압축 복구]\n"
            f"수정 파일: {total}개 ({files_summary})\n"
            f"QA 상태: PASS {state.get('qa_pass_count', 0)}개, FAIL {fails}개\n"
            f"보고서 작성: {'완료' if walkthrough else '미완료'}\n"
            f"{SYSTEM_REMINDER}"
        )

    else:
        print(f"[세션] {SYSTEM_REMINDER}")

    sys.exit(0)


if __name__ == "__main__":
    main()
