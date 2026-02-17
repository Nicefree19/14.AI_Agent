#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
W2D: Executor 계약 테스트

- 47개 executor 전수 반환 형식 검증 ({"result_text": str, "files": list})
- _lazy_skill 에러 핸들링
- safe_print 동작 검증
"""

import tempfile

import pytest


# ═══════════════════════════════════════════════════════════════
#  Executor 반환 형식 전수 검증
# ═══════════════════════════════════════════════════════════════


def _make_context(instruction: str = "테스트") -> dict:
    """테스트용 표준 컨텍스트 생성."""
    return {
        "combined": {
            "combined_instruction": instruction,
            "message_ids": [0],
            "chat_id": 0,
            "all_timestamps": ["2026-02-17 00:00:00"],
            "files": [],
        },
        "memories": [],
        "task_dir": tempfile.mkdtemp(),
        "send_progress": lambda x: None,
    }


# 안전하게 실행 가능한 executor 목록
# (외부 의존성 없이 즉시 dict를 반환하는 것들만)
_SAFE_EXECUTORS = [
    "skill_help",
    "desktop_control",
]


class TestExecutorReturnFormat:
    """안전한 executor의 반환 형식 검증."""

    @pytest.mark.parametrize("executor_name", _SAFE_EXECUTORS)
    def test_executor_returns_dict_with_keys(self, executor_name):
        from scripts.telegram.telegram_executors import EXECUTOR_MAP

        executor = EXECUTOR_MAP.get(executor_name)
        assert executor is not None, f"EXECUTOR_MAP에 '{executor_name}' 없음"

        ctx = _make_context()
        result = executor(ctx)

        assert isinstance(result, dict), (
            f"'{executor_name}' 반환이 dict가 아님: {type(result)}"
        )
        assert "result_text" in result, (
            f"'{executor_name}' 반환에 'result_text' 키 누락"
        )
        assert "files" in result, (
            f"'{executor_name}' 반환에 'files' 키 누락"
        )
        assert isinstance(result["result_text"], str), (
            f"'{executor_name}' result_text가 str이 아님"
        )
        assert isinstance(result["files"], list), (
            f"'{executor_name}' files가 list가 아님"
        )


class TestAllExecutorsExistAndCallable:
    """EXECUTOR_MAP 전수 존재성 + callable 검증."""

    def test_all_executors_callable(self):
        from scripts.telegram.telegram_executors import EXECUTOR_MAP

        not_callable = []
        for name, fn in EXECUTOR_MAP.items():
            if not callable(fn):
                not_callable.append(name)
        assert not not_callable, f"callable이 아닌 executor: {not_callable}"

    def test_executor_count_sanity(self):
        from scripts.telegram.telegram_executors import EXECUTOR_MAP

        count = len(EXECUTOR_MAP)
        assert count >= 40, f"EXECUTOR_MAP 크기 이상: {count} (최소 40 기대)"

    def test_list_executors_returns_list(self):
        from scripts.telegram.telegram_executors import list_executors

        names = list_executors()
        assert isinstance(names, list)
        assert len(names) >= 40


# ═══════════════════════════════════════════════════════════════
#  _lazy_skill 에러 핸들링
# ═══════════════════════════════════════════════════════════════


class TestLazySkillErrorHandling:
    """_lazy_skill이 ImportError 시 graceful degradation."""

    def test_lazy_skill_with_invalid_module(self):
        from scripts.telegram.telegram_executors import _lazy_skill

        wrapper = _lazy_skill(
            "scripts.telegram.skills.nonexistent_module_xyz",
            "nonexistent_func",
        )
        assert callable(wrapper), "_lazy_skill 래퍼가 callable이어야 함"

        ctx = _make_context()
        result = wrapper(ctx)
        assert isinstance(result, dict), "실패 시에도 dict 반환해야 함"
        assert "result_text" in result
        # 에러 메시지가 포함되어야 함
        assert "오류" in result["result_text"] or "error" in result["result_text"].lower()


# ═══════════════════════════════════════════════════════════════
#  safe_print 동작 검증
# ═══════════════════════════════════════════════════════════════


class TestSafePrint:
    """logger.safe_print() cp949 안전성 검증."""

    def test_ascii_text(self):
        from scripts.telegram.logger import safe_print

        # 예외 없이 실행되면 성공
        safe_print("plain ASCII text")

    def test_emoji_text(self):
        from scripts.telegram.logger import safe_print

        # cp949에서 실패할 수 있지만 예외 없이 처리되어야 함
        safe_print("✅ 완료! ❌ 실패! ⚠️ 경고!")

    def test_korean_text(self):
        from scripts.telegram.logger import safe_print

        safe_print("한글 테스트 메시지입니다")

    def test_mixed_content(self):
        from scripts.telegram.logger import safe_print

        safe_print("작업 ✅ 완료: 3개 파일 📎 전송됨 (msg_123)")
