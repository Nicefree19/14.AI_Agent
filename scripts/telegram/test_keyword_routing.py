#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
키워드 라우팅 회귀 테스트 (Keyword Routing Regression Tests)

False-positive 방지 및 True-positive 유지를 검증한다.

Usage:
    pytest scripts/telegram/test_keyword_routing.py -v
    python -m scripts.telegram.test_keyword_routing
"""

import os
import sys

import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Windows 콘솔 UTF-8 출력
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from scripts.telegram.telegram_executors import (
    get_executor,
    is_direct_skill,
    _is_complex_work_request,
    _run_claude_cli,
    _default_executor,
)


# ── TRUE POSITIVES: 단순 명령 → 키워드 스킬에 라우팅되어야 함 ──
TRUE_POSITIVE_CASES = [
    # (메시지, is_direct_skill이 True여야 함)
    ("스킬 목록", True),
    ("스킬", True),
    ("도움말", True),
    ("help", True),
    ("메일확인", True),
    ("최근메일", True),
    # 카카오톡 스킬은 pywinauto 직접 제어 → is_direct_skill=True (Step 2 직행)
    ("카톡읽기", True),
    ("카톡방목록", True),
    # 데스크톱 제어도 pywinauto 직접 제어로 전환 → is_direct_skill=True
    ("화면캡처", True),
    ("스크린샷", True),
    ("브리핑", True),
    ("엑셀분석", True),
    ("이슈조회 SEN-428", True),
    ("아침루틴", True),
    ("전체점검", True),
]

# ── FALSE POSITIVES: 복잡한 작업 지시 → Claude Code로 넘어가야 함 ──
FALSE_POSITIVE_CASES = [
    # (메시지, is_direct_skill이 False여야 함)
    # 원래 버그 케이스
    (
        "메일중 복합동 선제작 리스크 발주 관련 메일이 있어 거기에 복합동공사관련한 골조 물량이 "
        "정리된 시트가 있어 이걸 아주 정밀하게 분석해서 내가 앞으로 물량에 대한 질문시 이걸 "
        "기반으로 답변해주고, 특이사항으로 변경점에 따른 물량 변화를 검토해줄수있게 스킬구축해줘",
        False,
    ),
    # "이슈" 키워드 포함 복잡 작업
    (
        "이슈가 많이 발생하고 있는데 그 원인을 체계적으로 분석해서 보고서를 만들어줘",
        False,
    ),
    # "현황" 키워드 포함 복잡 작업
    (
        "현황을 파악해서 종합적으로 분석하고 개선방안을 제시해줘",
        False,
    ),
    # "검색" + "스킬" 키워드 포함 복잡 작업
    (
        "검색 기능을 구현해서 데이터베이스에서 효율적으로 찾을 수 있게 스킬을 만들어줘",
        False,
    ),
    # "메일" 키워드 포함 복잡 작업
    (
        "메일로 받은 자료를 정리하고 팀원들에게 공유할 수 있는 시스템을 구축해줘",
        False,
    ),
    # "일정" 키워드 포함 복잡 작업
    (
        "일정 관리 시스템을 새로 설계해서 프로젝트 전체에 적용할 수 있게 만들어줘",
        False,
    ),
    # "요약" 키워드 포함 복잡 작업
    (
        "요약본을 기반으로 전체 보고서를 다시 작성하고 임원진에게 보고할 자료를 준비해줘",
        False,
    ),
]

# ── COMPLEXITY GUARD 단위 테스트 ──
GUARD_CASES = [
    # (text, keyword, expected_complex)
    ("스킬 목록", "스킬", False),          # 짧은 단순 명령
    ("도움말", "도움말", False),             # 명시적 항상 매칭
    ("화면캡처", "화면캡처", False),          # 항상 매칭 키워드
    ("메일확인", "메일확인", False),          # 짧은 단순 명령 (4자 > 3자 임계)
    ("스킬", "스킬", False),                # 1단어 명령
    # 복합어 검출
    (
        "스킬구축해줘 이것저것 복잡한 작업을 정리해서 만들어줘",
        "스킬",
        True,
    ),
    # 키워드 + 조사 (짧은 메시지 → 단순)
    ("스킬을 보여줘", "스킬", False),
    # 빈 문자열
    ("", "스킬", False),
    # 긴 메시지 + 작업동사 (keyword가 4자 이상이라 compound 체크 안 함,
    # 하지만 verb suffix로 감지)
    (
        "이슈가 많이 발생하고 있는데 원인을 분석해서 보고서를 만들어줘",
        "이슈",
        True,
    ),
]


# ── pytest 테스트 ──

@pytest.mark.parametrize("text,expected", TRUE_POSITIVE_CASES,
                         ids=[c[0][:30] for c in TRUE_POSITIVE_CASES])
def test_true_positive(text, expected):
    """단순 명령이 키워드 스킬에 올바르게 라우팅되는지 확인."""
    result = is_direct_skill(text)
    assert result == expected, (
        f"'{text}' → expected direct_skill={expected}, got {result} "
        f"(executor={getattr(get_executor(text), '__name__', '?')})"
    )


@pytest.mark.parametrize("text,expected", FALSE_POSITIVE_CASES,
                         ids=[c[0][:30] for c in FALSE_POSITIVE_CASES])
def test_false_positive(text, expected):
    """복잡한 작업 지시가 Claude Code로 넘어가는지 확인."""
    result = is_direct_skill(text)
    assert result == expected, (
        f"'{text[:50]}...' → expected direct_skill={expected}, got {result} "
        f"(executor={getattr(get_executor(text), '__name__', '?')})"
    )


@pytest.mark.parametrize("text,kw,expected", GUARD_CASES,
                         ids=[f"{c[0][:20]}-{c[1]}" for c in GUARD_CASES])
def test_complexity_guard(text, kw, expected):
    """_is_complex_work_request() 단위 테스트."""
    result = _is_complex_work_request(text, kw)
    assert result == expected, (
        f"'{text[:40]}' kw='{kw}' → expected complex={expected}, got {result}"
    )


# ── 하위 호환: python -m scripts.telegram.test_keyword_routing ──

def main():
    print("=" * 60)
    print("  Keyword Routing Regression Tests (pytest)")
    print("=" * 60)
    return pytest.main([__file__, "-v"])


if __name__ == "__main__":
    sys.exit(main())
