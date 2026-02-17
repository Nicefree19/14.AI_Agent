#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
에러 분류 + 구조화 처리 모듈
=============================
에러를 심각도별로 분류하고 구조화된 로깅 수행.

사용법:
    from scripts.telegram.error_handler import classify_error, handle_error

    try:
        ...
    except Exception as exc:
        severity, category = classify_error(exc)
        handle_error(exc, severity, category, context={"task": "..."})
"""

from __future__ import annotations

from typing import Optional

from scripts.telegram.config import ErrorSeverity, is_enabled
from scripts.telegram.logger import get_logger

log = get_logger(__name__)

# ═══════════════════════════════════════════════════════════════
#  에러 타입 → 심각도 매핑
# ═══════════════════════════════════════════════════════════════

_ERROR_MAP: dict[type, tuple[ErrorSeverity, str]] = {
    # 파일 시스템
    FileNotFoundError: (ErrorSeverity.MEDIUM, "file_not_found"),
    PermissionError: (ErrorSeverity.HIGH, "permission_denied"),
    OSError: (ErrorSeverity.MEDIUM, "os_error"),
    # 네트워크
    ConnectionError: (ErrorSeverity.HIGH, "connection_error"),
    TimeoutError: (ErrorSeverity.HIGH, "timeout"),
    # 인코딩
    UnicodeEncodeError: (ErrorSeverity.LOW, "encoding_error"),
    UnicodeDecodeError: (ErrorSeverity.LOW, "decoding_error"),
    # 데이터
    ValueError: (ErrorSeverity.MEDIUM, "value_error"),
    KeyError: (ErrorSeverity.MEDIUM, "key_error"),
    TypeError: (ErrorSeverity.MEDIUM, "type_error"),
    # JSON
    # json.JSONDecodeError는 ValueError의 서브클래스
    # 인덱스
    IndexError: (ErrorSeverity.MEDIUM, "index_error"),
    # 모듈
    ImportError: (ErrorSeverity.CRITICAL, "import_error"),
    ModuleNotFoundError: (ErrorSeverity.CRITICAL, "module_not_found"),
    # 메모리
    MemoryError: (ErrorSeverity.CRITICAL, "memory_error"),
    # 런타임
    RuntimeError: (ErrorSeverity.HIGH, "runtime_error"),
    RecursionError: (ErrorSeverity.CRITICAL, "recursion_error"),
}

# 카카오톡 예외 등록 (지연 import로 순환 방지)
try:
    from scripts.telegram.kakao_pywinauto import (
        KakaoActivationError,
        KakaoNotRunningError,
    )

    _ERROR_MAP[KakaoNotRunningError] = (ErrorSeverity.HIGH, "kakao_not_running")
    _ERROR_MAP[KakaoActivationError] = (ErrorSeverity.MEDIUM, "kakao_activation_failed")
except ImportError:
    pass  # pywinauto 미설치 환경에서도 모듈 로드 가능


def classify_error(exc: BaseException) -> tuple[ErrorSeverity, str]:
    """예외를 (심각도, 카테고리) 튜플로 분류.

    등록된 예외 타입은 정확 매핑, 미등록은 MRO 순서로 탐색,
    최종 미매칭 시 MEDIUM/"unknown" 반환.
    """
    exc_type = type(exc)

    # 정확 매핑
    if exc_type in _ERROR_MAP:
        return _ERROR_MAP[exc_type]

    # MRO 기반 상위 타입 탐색
    for parent in exc_type.__mro__:
        if parent in _ERROR_MAP:
            return _ERROR_MAP[parent]

    return ErrorSeverity.MEDIUM, "unknown"


def handle_error(
    exc: BaseException,
    severity: ErrorSeverity,
    category: str,
    context: Optional[dict] = None,
) -> None:
    """분류된 에러를 구조화 로깅.

    feature flag "error_classification" OFF → 기존 동작 유지 (단순 warning).
    """
    ctx_str = ""
    if context:
        ctx_str = " | ".join(f"{k}={v}" for k, v in context.items())

    if not is_enabled("error_classification"):
        # flag OFF: 기존 호환 — 단순 warning 로그
        log.warning("에러 발생: %s (%s) [%s]", exc, category, ctx_str)
        return

    # flag ON: 심각도별 구조화 로깅
    msg = (
        f"[{severity.value.upper()}] {category}: {exc}"
        f" | context={{{ctx_str}}}"
    )

    if severity == ErrorSeverity.CRITICAL:
        log.critical(msg)
    elif severity == ErrorSeverity.HIGH:
        log.error(msg)
    elif severity == ErrorSeverity.MEDIUM:
        log.warning(msg)
    else:  # LOW
        log.info(msg)
