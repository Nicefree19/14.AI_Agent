#!/usr/bin/env python
"""
stop_guardian.py - 시스템 1+4: 리뷰 강제 + 계획 검증 훅
이벤트: Stop

Claude가 작업을 종료하려 할 때 4대 시스템 이행 여부를 검증.
- 수정 3개+ 파일 & QA FAIL → 차단 (exit 2)
- 수정 3개+ 파일 & walkthrough 미감지 → 차단 (exit 2)
- stop_hook_active=true → 무한루프 방지 (exit 0)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hook_utils import (
    read_stdin_json,
    write_stderr,
    load_session_state,
    save_session_state,
    detect_walkthrough,
)


def main():
    data = read_stdin_json()
    state = load_session_state()

    # 무한루프 방지: stop_hook이 이미 발동한 후 재시도면 통과
    if state.get("stop_hook_active"):
        # 플래그 리셋 후 통과
        state["stop_hook_active"] = False
        save_session_state(state)
        sys.exit(0)

    total_mods = state.get("total_modifications", 0)
    qa_fails = state.get("qa_fail_count", 0)
    walkthrough = state.get("walkthrough_detected", False)

    # last_assistant_message에서 walkthrough 재확인
    last_msg = data.get("last_assistant_message", "")
    if last_msg and detect_walkthrough(last_msg):
        walkthrough = True
        state["walkthrough_detected"] = True
        save_session_state(state)

    # 수정 파일 0개 → 무조건 통과
    if total_mods == 0:
        sys.exit(0)

    # 수정 1-2개 → 경고만 (차단 안 함)
    if total_mods < 3:
        sys.exit(0)

    # === 수정 3개 이상: 엄격 검증 ===

    # 검증 1: QA FAIL 존재
    if qa_fails > 0:
        fail_files = [
            f for f, info in state.get("modified_files", {}).items()
            if info.get("qa_result") == "FAIL"
        ]
        fail_list = "\n".join(f"  - {f}" for f in fail_files[:5])
        state["stop_hook_active"] = True
        save_session_state(state)
        write_stderr(
            f"[품질 게이트 미통과] 아래 파일의 품질 검사가 실패했습니다:\n"
            f"{fail_list}\n"
            f"→ 오류를 수정한 후 다시 종료해주세요.\n"
        )
        sys.exit(2)

    # 검증 2: walkthrough 미작성
    if not walkthrough:
        mod_files = list(state.get("modified_files", {}).keys())[:5]
        files_list = "\n".join(f"  - {f}" for f in mod_files)
        state["stop_hook_active"] = True
        save_session_state(state)
        write_stderr(
            f"[작업 보고서 미작성] {total_mods}개 파일을 수정했으나 "
            f"작업 보고서(walkthrough)가 감지되지 않았습니다.\n"
            f"수정된 파일:\n{files_list}\n"
            f"→ 변경 내역, 검증 결과, 셀프 리뷰를 포함한 보고서를 작성해주세요.\n"
        )
        sys.exit(2)

    # 모든 검증 통과
    sys.exit(0)


if __name__ == "__main__":
    main()
