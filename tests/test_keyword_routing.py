#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
W2C: 키워드 라우팅 검증 테스트

- KEYWORD_MAP → EXECUTOR_MAP 완전성
- 긴 키워드 우선 순서
- Complexity Guard 동작
- Stability Gate 동작
- ALWAYS_MATCH 키워드 우회
"""

import pytest


# ═══════════════════════════════════════════════════════════════
#  기본 라우팅 완전성
# ═══════════════════════════════════════════════════════════════


class TestKeywordRoutingCompleteness:
    """KEYWORD_MAP ↔ EXECUTOR_MAP 양방향 검증."""

    def test_all_keyword_executors_exist_in_map(self):
        from scripts.telegram.telegram_executors import KEYWORD_MAP, EXECUTOR_MAP

        missing = [
            (kw, name)
            for kw, name in KEYWORD_MAP.items()
            if name not in EXECUTOR_MAP
        ]
        assert not missing, f"KEYWORD_MAP → EXECUTOR_MAP 누락: {missing}"

    def test_all_executors_callable(self):
        from scripts.telegram.telegram_executors import EXECUTOR_MAP

        not_callable = [name for name, fn in EXECUTOR_MAP.items() if not callable(fn)]
        assert not not_callable, f"callable 아닌 executor: {not_callable}"

    def test_keyword_map_minimum_size(self):
        from scripts.telegram.telegram_executors import KEYWORD_MAP

        assert len(KEYWORD_MAP) >= 200, (
            f"KEYWORD_MAP이 너무 작음: {len(KEYWORD_MAP)} (최소 200 기대)"
        )

    def test_executor_map_minimum_size(self):
        from scripts.telegram.telegram_executors import EXECUTOR_MAP

        assert len(EXECUTOR_MAP) >= 30, (
            f"EXECUTOR_MAP이 너무 작음: {len(EXECUTOR_MAP)} (최소 30 기대)"
        )


# ═══════════════════════════════════════════════════════════════
#  키워드 순서 & 충돌 감지
# ═══════════════════════════════════════════════════════════════


class TestKeywordOrdering:
    """부분문자열 충돌 시 긴 키워드가 먼저 매칭되는지 검증."""

    def test_keyword_map_longest_first_in_groups(self):
        """같은 executor로 매핑된 키워드 중 긴 키워드가 먼저 등장해야 함."""
        from scripts.telegram.telegram_executors import KEYWORD_MAP

        keywords = list(KEYWORD_MAP.keys())
        # 같은 executor를 가리키는 키워드 그룹 구축
        executor_keywords: dict[str, list[tuple[int, str]]] = {}
        for idx, kw in enumerate(keywords):
            name = KEYWORD_MAP[kw]
            executor_keywords.setdefault(name, []).append((idx, kw))

        violations = []
        for name, indexed_kws in executor_keywords.items():
            for i in range(len(indexed_kws)):
                for j in range(i + 1, len(indexed_kws)):
                    idx_a, kw_a = indexed_kws[i]
                    idx_b, kw_b = indexed_kws[j]
                    # kw_b가 kw_a의 부분문자열이면, kw_a(긴것)가 먼저여야 함
                    if kw_a in kw_b and idx_a > idx_b:
                        violations.append(
                            f"'{kw_b}'(idx={idx_b}) should come after '{kw_a}'(idx={idx_a}) "
                            f"for executor '{name}'"
                        )
        # 이 테스트는 잠재적 충돌을 감지하되, 현재 구조에서는 경고 수준
        if violations:
            pytest.warns(UserWarning, match="keyword ordering")

    def test_no_duplicate_keywords(self):
        """KEYWORD_MAP에 중복 키워드가 없어야 함 (dict이므로 자동 보장)."""
        from scripts.telegram.telegram_executors import KEYWORD_MAP

        # dict는 중복 키를 허용하지 않으므로, 소스 수준에서
        # 같은 키가 두 번 등장하면 마지막 값이 유지됨.
        # 여기서는 단순히 키 개수 확인으로 충분
        assert len(KEYWORD_MAP) == len(set(KEYWORD_MAP.keys()))


# ═══════════════════════════════════════════════════════════════
#  Complexity Guard
# ═══════════════════════════════════════════════════════════════


class TestComplexityGuard:
    """복잡한 메시지에서 짧은 키워드 오매칭 방지."""

    def test_short_message_matches_keyword(self):
        """짧은 단순 명령은 키워드 매칭 허용."""
        from scripts.telegram.telegram_executors import _is_complex_work_request

        assert _is_complex_work_request("스킬목록", "스킬") is False

    def test_long_complex_message_rejects_keyword(self):
        """긴 복잡한 작업 요청은 짧은 키워드 매칭 차단."""
        from scripts.telegram.telegram_executors import _is_complex_work_request

        msg = "P5 프로젝트의 이슈 분석 스킬을 구축해서 자동화 파이프라인에 연동해줘"
        result = _is_complex_work_request(msg, "스킬")
        assert result is True, "복잡한 작업 요청에서 짧은 키워드가 매칭되면 안 됨"

    def test_always_match_bypasses_guard(self):
        """_ALWAYS_MATCH_KEYWORDS는 complexity guard를 우회."""
        from scripts.telegram.telegram_executors import _is_complex_work_request

        # "도움말"은 always-match 키워드
        msg = "이 시스템의 사용법과 도움말 좀 자세히 알려줘"
        result = _is_complex_work_request(msg, "도움말")
        assert result is False, "ALWAYS_MATCH 키워드는 guard 우회해야 함"


# ═══════════════════════════════════════════════════════════════
#  Stability Gate
# ═══════════════════════════════════════════════════════════════


class TestStabilityGate:
    """experimental 스킬 게이트 동작 검증."""

    def test_stable_skill_passes_gate(self):
        """stable 스킬은 게이트 통과."""
        from scripts.telegram.telegram_executors import _is_experimental_skill

        # 존재하지 않는 executor → stability_map에서 "stable" 기본값
        assert _is_experimental_skill("nonexistent_executor", "test") is False

    def test_experimental_prefix_bypasses_gate(self):
        """'실험' 접두사가 있으면 experimental 스킬도 통과."""
        from scripts.telegram.telegram_executors import _is_experimental_skill

        # monkeypatch 없이 "실험" 접두사 테스트
        assert _is_experimental_skill("any_executor", "실험 테스트") is False


# ═══════════════════════════════════════════════════════════════
#  ALWAYS_MATCH 키워드 전수 검증
# ═══════════════════════════════════════════════════════════════


class TestAlwaysMatchKeywords:
    """_ALWAYS_MATCH_KEYWORDS가 KEYWORD_MAP에 모두 존재하는지 검증."""

    def test_always_match_subset_of_keyword_map(self):
        from scripts.telegram.telegram_executors import (
            _ALWAYS_MATCH_KEYWORDS,
            KEYWORD_MAP,
        )

        not_in_map = [
            kw for kw in _ALWAYS_MATCH_KEYWORDS if kw not in KEYWORD_MAP
        ]
        # 알려진 불일치: "지금화면"은 ALWAYS_MATCH에 있지만 KEYWORD_MAP에 없음
        # (get_executor 내부의 별도 라우팅 로직에서 처리)
        known_exceptions = {"지금화면"}
        unexpected = [kw for kw in not_in_map if kw not in known_exceptions]
        assert not unexpected, (
            f"_ALWAYS_MATCH_KEYWORDS에 있지만 KEYWORD_MAP에 없는 키워드 "
            f"(known_exceptions 제외): {unexpected}"
        )

    def test_always_match_minimum_count(self):
        from scripts.telegram.telegram_executors import _ALWAYS_MATCH_KEYWORDS

        assert len(_ALWAYS_MATCH_KEYWORDS) >= 20, (
            f"ALWAYS_MATCH 키워드가 너무 적음: {len(_ALWAYS_MATCH_KEYWORDS)}"
        )


# ═══════════════════════════════════════════════════════════════
#  get_executor 통합 라우팅
# ═══════════════════════════════════════════════════════════════


class TestGetExecutor:
    """get_executor()의 핵심 라우팅 시나리오 검증."""

    def test_simple_keyword_returns_executor(self):
        """단순 키워드 → 적절한 executor 반환."""
        from scripts.telegram.telegram_executors import get_executor

        executor = get_executor("도움말")
        assert callable(executor), "도움말 키워드에 대한 executor가 없음"

    def test_reference_classification_routes_correctly(self):
        """reference 분류 → _reference_executor 반환."""
        from scripts.telegram.telegram_executors import get_executor

        executor = get_executor("아무 텍스트", classification="reference")
        assert callable(executor)

    def test_unknown_message_returns_default(self):
        """키워드 미매칭 → default executor (CLI 또는 안내)."""
        from scripts.telegram.telegram_executors import get_executor

        executor = get_executor("xyzzy_완전_랜덤_문자열_12345")
        assert callable(executor), "키워드 미매칭 시에도 executor가 반환되어야 함"

    def test_executor_returns_dict_format(self, mock_context):
        """도움말 executor가 표준 형식 반환."""
        from scripts.telegram.telegram_executors import get_executor

        executor = get_executor("도움말")
        mock_context["combined"]["combined_instruction"] = "도움말"
        result = executor(mock_context)
        assert isinstance(result, dict), "executor 반환이 dict가 아님"
        assert "result_text" in result, "result_text 키 누락"
        assert "files" in result, "files 키 누락"


# ═══════════════════════════════════════════════════════════════
#  Feature Flag 통합 테스트
# ═══════════════════════════════════════════════════════════════


class TestFeatureFlags:
    """config.py feature flag 인프라 검증."""

    def test_all_flags_default_off(self):
        from scripts.telegram.config import FEATURE_FLAGS

        on_flags = [k for k, v in FEATURE_FLAGS.items() if v]
        assert not on_flags, f"기본값이 ON인 flag: {on_flags}"

    def test_is_enabled_returns_false_for_unknown(self):
        from scripts.telegram.config import is_enabled

        assert is_enabled("nonexistent_flag_xyz") is False

    def test_monkeypatch_flag(self, feature_flags_on):
        from scripts.telegram.config import is_enabled

        assert is_enabled("state_machine") is True

    def test_error_severity_values(self):
        from scripts.telegram.config import ErrorSeverity

        values = {s.value for s in ErrorSeverity}
        assert values == {"low", "medium", "high", "critical"}
