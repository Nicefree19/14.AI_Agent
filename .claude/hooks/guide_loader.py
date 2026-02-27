#!/usr/bin/env python
"""
guide_loader.py - 시스템 2: 가이드라인 자동 주입 훅
이벤트: PreToolUse (Write|Edit), UserPromptSubmit

파일 수정 전 또는 사용자 프롬프트 제출 시,
관련 가이드라인을 additionalContext로 자동 주입한다.
"""
import sys
import json
from pathlib import Path

# hook_utils 임포트 (같은 디렉토리)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from hook_utils import (
    read_stdin_json,
    write_stdout_json,
    match_path_triggers,
    match_keyword_triggers,
    load_guide_summary,
)


def handle_pre_tool_use(data: dict) -> dict | None:
    """PreToolUse (Write|Edit): 파일 경로에서 관련 가이드라인 매칭."""
    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")
    if not file_path:
        return None

    matched_guides = match_path_triggers(file_path)
    if not matched_guides:
        return None

    # 가이드라인 요약 수집
    summaries = []
    for guide in matched_guides:
        summary = load_guide_summary(guide)
        if summary:
            guide_name = Path(guide).stem
            summaries.append(f"[{guide_name}]\n{summary}")

    if not summaries:
        return None

    context = "[자동 매뉴얼 활성화]\n" + "\n---\n".join(summaries)
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "additionalContext": context
        }
    }


def handle_user_prompt(data: dict) -> dict | None:
    """UserPromptSubmit: 프롬프트 키워드에서 관련 가이드라인 매칭."""
    prompt = data.get("prompt", "")
    if not prompt:
        return None

    matched_guides = match_keyword_triggers(prompt)
    if not matched_guides:
        return None

    # 중복 제거
    unique_guides = list(dict.fromkeys(matched_guides))

    summaries = []
    for guide in unique_guides[:3]:  # 최대 3개 가이드라인 (토큰 절약)
        summary = load_guide_summary(guide)
        if summary:
            guide_name = Path(guide).stem
            summaries.append(f"[{guide_name}]\n{summary}")

    if not summaries:
        return None

    context = "[자동 매뉴얼 활성화]\n" + "\n---\n".join(summaries)
    return {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": context
        }
    }


def main():
    data = read_stdin_json()

    # 이벤트 타입 판별 (tool_name 존재 → PreToolUse, 아니면 UserPromptSubmit)
    if data.get("tool_name"):
        result = handle_pre_tool_use(data)
    else:
        result = handle_user_prompt(data)

    if result:
        write_stdout_json(result)

    sys.exit(0)


if __name__ == "__main__":
    main()
