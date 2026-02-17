#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
핵심 E2E 테스트 — 5개 시나리오

E2E-1: 키워드 라우팅 완전성
E2E-2: telegram_bot API 흐름
E2E-3: 스킬 임포트 체인
E2E-4: Executor 결과 형식
E2E-5: 메모리 시스템
"""

import importlib
import os
import sys
import tempfile

import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# ═══════════════════════════════════════════════════════════════
#  E2E-1: 키워드 라우팅 완전성
# ═══════════════════════════════════════════════════════════════

class TestE2E1_KeywordRoutingCompleteness:
    """KEYWORD_MAP의 모든 executor가 EXECUTOR_MAP에 존재하고 callable인지 검증."""

    def test_all_keyword_executors_exist(self):
        from scripts.telegram.telegram_executors import KEYWORD_MAP, EXECUTOR_MAP
        missing = []
        for keyword, executor_name in KEYWORD_MAP.items():
            if executor_name not in EXECUTOR_MAP:
                missing.append((keyword, executor_name))
        assert not missing, f"KEYWORD_MAP → EXECUTOR_MAP 누락: {missing}"

    def test_all_executors_callable(self):
        from scripts.telegram.telegram_executors import EXECUTOR_MAP
        not_callable = []
        for name, executor in EXECUTOR_MAP.items():
            if not callable(executor):
                not_callable.append(name)
        assert not not_callable, f"callable이 아닌 executor: {not_callable}"

    def test_keyword_map_not_empty(self):
        from scripts.telegram.telegram_executors import KEYWORD_MAP
        assert len(KEYWORD_MAP) > 0, "KEYWORD_MAP이 비어있음"

    def test_executor_map_not_empty(self):
        from scripts.telegram.telegram_executors import EXECUTOR_MAP
        assert len(EXECUTOR_MAP) > 0, "EXECUTOR_MAP이 비어있음"


# ═══════════════════════════════════════════════════════════════
#  E2E-2: telegram_bot API 흐름
# ═══════════════════════════════════════════════════════════════

class TestE2E2_TelegramBotAPI:
    """combine_tasks 합산 및 get_task_dir 디렉토리 생성 검증."""

    def test_combine_tasks_sums_correctly(self):
        from scripts.telegram.telegram_bot import combine_tasks
        pending = [
            {
                "message_id": 1,
                "chat_id": 12345,
                "instruction": "첫 번째 지시",
                "timestamp": "2026-02-16 10:00:00",
                "files": [],
                "context_24h": "",
                "user_name": "test",
            },
            {
                "message_id": 2,
                "chat_id": 12345,
                "instruction": "두 번째 지시",
                "timestamp": "2026-02-16 10:01:00",
                "files": [],
                "context_24h": "",
                "user_name": "test",
            },
        ]
        combined = combine_tasks(pending, include_24h_context=False)
        assert "message_ids" in combined
        assert len(combined["message_ids"]) == 2
        assert "combined_instruction" in combined
        assert "첫 번째" in combined["combined_instruction"]
        assert "두 번째" in combined["combined_instruction"]

    def test_get_task_dir_creates_directory(self):
        from scripts.telegram.telegram_bot import get_task_dir
        task_dir = get_task_dir(99999)
        assert os.path.isdir(task_dir), f"task_dir 생성 실패: {task_dir}"
        # cleanup
        try:
            os.rmdir(task_dir)
        except OSError:
            pass


# ═══════════════════════════════════════════════════════════════
#  E2E-3: 스킬 임포트 체인
# ═══════════════════════════════════════════════════════════════

SKILL_MODULES = [
    "scripts.telegram.skills.utility_skills",
    "scripts.telegram.skills.analysis_skills",
    "scripts.telegram.skills.generation_skills",
    "scripts.telegram.skills.intelligence_skills",
    "scripts.telegram.skills.google_skills",
    "scripts.telegram.skills.email_skills",
    "scripts.telegram.skills.kakao_skills",
    "scripts.telegram.skills.kakao_live_skills",
    "scripts.telegram.skills.engineering_skills",
    "scripts.telegram.skills.quantity_skills",
    "scripts.telegram.skills.system_skills",
    "scripts.telegram.skills.dashboard_skills",
    "scripts.telegram.skills.kakao_summary_skills",
    "scripts.telegram.skills.quantity_monitor_skills",
    "scripts.telegram.skills.traceability_skills",
    "scripts.telegram.skills.desktop_skills",
]


class TestE2E3_SkillImportChain:
    """모든 스킬 모듈이 ImportError 없이 로딩되는지 검증."""

    @pytest.mark.parametrize("module_path", SKILL_MODULES,
                             ids=[m.split(".")[-1] for m in SKILL_MODULES])
    def test_skill_module_imports(self, module_path):
        mod = importlib.import_module(module_path)
        assert mod is not None, f"{module_path} import 실패"


# ═══════════════════════════════════════════════════════════════
#  E2E-4: Executor 결과 형식
# ═══════════════════════════════════════════════════════════════

class TestE2E4_ExecutorResultFormat:
    """skill_help, metrics executor가 {"result_text", "files"} 형식 반환 검증."""

    def _make_context(self, instruction="테스트"):
        return {
            "combined": {
                "combined_instruction": instruction,
                "message_ids": [0],
                "chat_id": 0,
                "all_timestamps": ["2026-02-16 00:00:00"],
                "files": [],
            },
            "memories": [],
            "task_dir": tempfile.mkdtemp(),
            "send_progress": lambda x: None,
        }

    def test_skill_help_format(self):
        from scripts.telegram.skills.utility_skills import run_skill_help
        result = run_skill_help(self._make_context("도움말"))
        assert isinstance(result, dict), "skill_help 반환이 dict가 아님"
        assert "result_text" in result, "result_text 키 누락"
        assert "files" in result, "files 키 누락"
        assert isinstance(result["result_text"], str)
        assert isinstance(result["files"], list)

    def test_desktop_control_format(self):
        from scripts.telegram.skills.desktop_skills import run_desktop_control
        ctx = self._make_context("프로그램목록")
        result = run_desktop_control(ctx)
        assert isinstance(result, dict), "desktop_control 반환이 dict가 아님"
        assert "result_text" in result
        assert "files" in result


# ═══════════════════════════════════════════════════════════════
#  E2E-5: 메모리 시스템
# ═══════════════════════════════════════════════════════════════

class TestE2E5_MemorySystem:
    """search_memory 키워드 검색 동작 검증."""

    def test_search_memory_returns_list(self):
        from scripts.telegram.telegram_bot import search_memory
        results = search_memory(keyword="NONEXISTENT_TEST_KEYWORD_XYZ")
        assert isinstance(results, list), "search_memory가 list를 반환하지 않음"

    def test_search_memory_by_message_id(self):
        from scripts.telegram.telegram_bot import search_memory
        results = search_memory(message_id=0)
        assert isinstance(results, list), "search_memory(message_id=0)가 list를 반환하지 않음"
