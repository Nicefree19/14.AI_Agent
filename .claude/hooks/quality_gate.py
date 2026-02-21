#!/usr/bin/env python
"""
quality_gate.py - 시스템 3: 품질 검사 자동 실행 훅
이벤트: PostToolUse (Write|Edit)

파일 수정 후 자동으로 품질 검사를 실행하고,
결과를 session_state.json에 기록 + additionalContext로 주입.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hook_utils import (
    read_stdin_json,
    write_stdout_json,
    load_session_state,
    save_session_state,
    run_quality_check,
)


def main():
    data = read_stdin_json()

    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")
    if not file_path:
        sys.exit(0)

    # 훅 자체 파일은 검사 스킵 (.claude/hooks/ 내부)
    try:
        resolved = Path(file_path).resolve()
        hooks_dir = Path(__file__).resolve().parent
        if str(resolved).startswith(str(hooks_dir)):
            sys.exit(0)
    except Exception:
        pass

    # 품질 검사 실행
    qa = run_quality_check(file_path)

    # 세션 상태 업데이트
    state = load_session_state()
    now = datetime.now(timezone.utc).isoformat()

    # 상대 경로로 저장
    try:
        from hook_utils import PROJECT_DIR
        rel_path = str(Path(file_path).resolve().relative_to(PROJECT_DIR)).replace("\\", "/")
    except (ValueError, Exception):
        rel_path = file_path

    state["modified_files"][rel_path] = {
        "time": now,
        "qa_result": qa["qa_result"],
        "checks": qa["checks"],
    }
    state["total_modifications"] = len(state["modified_files"])

    # PASS/FAIL 카운트 재계산
    state["qa_pass_count"] = sum(
        1 for f in state["modified_files"].values() if f.get("qa_result") == "PASS"
    )
    state["qa_fail_count"] = sum(
        1 for f in state["modified_files"].values() if f.get("qa_result") == "FAIL"
    )

    save_session_state(state)

    # 결과를 additionalContext로 주입
    if qa["qa_result"] == "FAIL":
        error_detail = "\n".join(f"  - {e}" for e in qa["errors"])
        context = (
            f"[품질 게이트 FAIL] {rel_path}\n"
            f"검사 결과: {', '.join(qa['checks'])}\n"
            f"오류:\n{error_detail}\n"
            f"→ 즉시 수정이 필요합니다."
        )
    else:
        context = (
            f"[품질 게이트 PASS] {rel_path}\n"
            f"검사 결과: {', '.join(qa['checks'])}"
        )

    write_stdout_json({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": context
        }
    })

    sys.exit(0)


if __name__ == "__main__":
    main()
