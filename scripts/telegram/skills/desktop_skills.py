#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
데스크톱 제어 스킬 모듈 (pywinauto 직접 실행)
================================================
MCP 의존성 없이 pywinauto/PowerShell로 데스크톱을 직접 제어.
Step 2(python_runner)에서 직행 실행 가능 (LLM 토큰 0).

스킬:
  - 화면캡처/스크린샷: take_screenshot
  - 프로그램목록: list_running_apps
  - 앱 활성화/전환: activate_app
  - 앱 실행: launch_app
  - 타이핑/입력: type_text_to_active
  - 클릭: click_at_coords
  - 시스템정보: get_system_info
"""

from __future__ import annotations

import re
from typing import Dict


# ═══════════════════════════════════════════════════════════════
#  서브 키워드 라우팅 테이블
# ═══════════════════════════════════════════════════════════════

_SUB_KEYWORDS = {
    "screenshot": [
        "화면캡처", "스크린샷", "screenshot", "지금화면", "캡처",
        "화면보여", "화면찍", "현재화면",
    ],
    "list_apps": [
        "프로그램목록", "실행중", "프로세스", "열려있는",
        "프로그램리스트", "앱목록", "running",
    ],
    "activate": [
        "화면전환", "프로그램전환", "앱전환", "활성화",
        "포그라운드", "전환",
    ],
    "launch": [
        "프로그램열기", "실행해", "열어줘", "실행",
        "프로그램실행", "앱열기", "launch", "open",
    ],
    "type_text": [
        "타이핑", "입력해", "타이핑해", "텍스트입력",
        "타자", "입력",
    ],
    "click": [
        "클릭", "마우스", "click", "누르", "눌러",
    ],
    "sysinfo": [
        "시스템정보", "시스템상태", "컴퓨터정보", "PC정보",
        "sysinfo", "systeminfo",
    ],
}


def _detect_sub_action(instruction: str) -> str | None:
    """지시문에서 서브 키워드를 감지하여 액션 이름 반환."""
    text_lower = instruction.lower().replace(" ", "")
    for action, keywords in _SUB_KEYWORDS.items():
        for kw in keywords:
            if kw.lower().replace(" ", "") in text_lower:
                return action
    return None


def _extract_app_name(instruction: str) -> str:
    """지시문에서 앱 이름 추출."""
    # "크롬 열어줘", "outlook 실행해줘" 등에서 앱 이름 추출
    # 키워드 제거 후 남은 핵심 명사 추출
    remove_patterns = [
        r"프로그램\s*열기", r"실행해\s*줘?", r"열어\s*줘?",
        r"프로그램\s*실행", r"앱\s*열기", r"launch", r"open",
        r"화면\s*전환", r"프로그램\s*전환", r"활성화",
        r"으?로\s*전환", r"해\s*줘", r"해\s*주세요",
    ]
    text = instruction.strip()
    for pat in remove_patterns:
        text = re.sub(pat, "", text, flags=re.IGNORECASE).strip()

    # 남은 텍스트가 앱 이름
    return text.strip() if text.strip() else ""


def _extract_coords(instruction: str) -> tuple[int, int] | None:
    """지시문에서 좌표 추출 (x, y) 또는 (x y)."""
    m = re.search(r"(\d{2,4})\s*[,\s]\s*(\d{2,4})", instruction)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None


def _extract_text_to_type(instruction: str) -> str:
    """지시문에서 입력할 텍스트 추출."""
    # 따옴표 안의 텍스트
    m = re.search(r'["\'](.+?)["\']', instruction)
    if m:
        return m.group(1)
    # "입력해줘" 등 키워드 앞의 텍스트
    remove_patterns = [
        r"타이핑\s*해?\s*줘?", r"입력\s*해?\s*줘?",
        r"타이핑", r"텍스트\s*입력",
    ]
    text = instruction.strip()
    for pat in remove_patterns:
        text = re.sub(pat, "", text, flags=re.IGNORECASE).strip()
    return text.strip()


# ═══════════════════════════════════════════════════════════════
#  메인 executor
# ═══════════════════════════════════════════════════════════════

def run_desktop_control(context: dict) -> dict:
    """데스크톱 제어 executor — pywinauto/PowerShell 직접 실행.

    Args:
        context: 표준 executor context (combined, memories, task_dir, send_progress)

    Returns:
        {"result_text": str, "files": list[str]}
    """
    from scripts.telegram.desktop_pywinauto import (
        take_screenshot,
        list_running_apps,
        activate_app,
        launch_app,
        type_text_to_active,
        click_at_coords,
        get_system_info,
    )

    send_progress = context.get("send_progress", lambda x: None)
    combined = context["combined"]
    instruction = combined["combined_instruction"]
    task_dir = context.get("task_dir", "")

    send_progress("🖥️ 데스크톱 제어 작업을 실행합니다...")

    # 서브 키워드 감지
    action = _detect_sub_action(instruction)

    if action == "screenshot":
        return take_screenshot(task_dir)

    if action == "list_apps":
        return list_running_apps()

    if action == "activate":
        app_name = _extract_app_name(instruction)
        if not app_name:
            return {"result_text": "⚠️ 전환할 프로그램 이름을 알려주세요.", "files": []}
        return activate_app(app_name)

    if action == "launch":
        app_name = _extract_app_name(instruction)
        if not app_name:
            return {"result_text": "⚠️ 실행할 프로그램 이름을 알려주세요.", "files": []}
        return launch_app(app_name)

    if action == "type_text":
        text = _extract_text_to_type(instruction)
        if not text:
            return {"result_text": "⚠️ 입력할 텍스트를 알려주세요.", "files": []}
        return type_text_to_active(text)

    if action == "click":
        coords = _extract_coords(instruction)
        if not coords:
            return {"result_text": "⚠️ 클릭할 좌표를 알려주세요. (예: 500, 300)", "files": []}
        return click_at_coords(coords[0], coords[1])

    if action == "sysinfo":
        return get_system_info()

    # 서브 키워드 미감지 → legacy fallback
    return _fallback_legacy(context)


def _fallback_legacy(context: dict) -> dict:
    """복잡한 자연어 지시 → Claude CLI legacy 위임."""
    try:
        from scripts.telegram.telegram_executors import _run_desktop_control_legacy
        return _run_desktop_control_legacy(context)
    except (ImportError, AttributeError):
        return {
            "result_text": (
                "⚠️ 데스크톱 제어 명령을 인식하지 못했습니다.\n\n"
                "사용 가능한 명령:\n"
                "- 화면캡처/스크린샷\n"
                "- 프로그램목록\n"
                "- 프로그램 전환 (예: 크롬 전환)\n"
                "- 프로그램 실행 (예: 메모장 열어줘)\n"
                "- 타이핑 (예: \"텍스트\" 입력해줘)\n"
                "- 클릭 (예: 500, 300 클릭)\n"
                "- 시스템정보"
            ),
            "files": [],
        }
