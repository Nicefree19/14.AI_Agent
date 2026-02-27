#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
W3C: 에러 분류 모듈 테스트

- classify_error() 매핑 정확성
- MRO 기반 상위 타입 탐색
- handle_error() flag ON/OFF 동작
- _lazy_skill 통합 및 telegram_runner 통합 존재 검증
"""

import logging

import pytest


# ═══════════════════════════════════════════════════════════════
#  classify_error() 매핑 검증
# ═══════════════════════════════════════════════════════════════


class TestClassifyError:
    """예외 타입 → (severity, category) 정확 매핑."""

    def test_file_not_found(self):
        from scripts.telegram.config import ErrorSeverity
        from scripts.telegram.error_handler import classify_error

        sev, cat = classify_error(FileNotFoundError("missing.txt"))
        assert sev == ErrorSeverity.MEDIUM
        assert cat == "file_not_found"

    def test_connection_error(self):
        from scripts.telegram.config import ErrorSeverity
        from scripts.telegram.error_handler import classify_error

        sev, cat = classify_error(ConnectionError("refused"))
        assert sev == ErrorSeverity.HIGH
        assert cat == "connection_error"

    def test_import_error_is_critical(self):
        from scripts.telegram.config import ErrorSeverity
        from scripts.telegram.error_handler import classify_error

        sev, cat = classify_error(ImportError("no module"))
        assert sev == ErrorSeverity.CRITICAL
        assert cat == "import_error"

    def test_module_not_found_is_critical(self):
        from scripts.telegram.config import ErrorSeverity
        from scripts.telegram.error_handler import classify_error

        sev, cat = classify_error(ModuleNotFoundError("xyz"))
        assert sev == ErrorSeverity.CRITICAL
        assert cat == "module_not_found"

    def test_timeout_error(self):
        from scripts.telegram.config import ErrorSeverity
        from scripts.telegram.error_handler import classify_error

        sev, cat = classify_error(TimeoutError("timed out"))
        assert sev == ErrorSeverity.HIGH
        assert cat == "timeout"

    def test_unicode_encode_error_is_low(self):
        from scripts.telegram.config import ErrorSeverity
        from scripts.telegram.error_handler import classify_error

        exc = UnicodeEncodeError("utf-8", "", 0, 1, "reason")
        sev, cat = classify_error(exc)
        assert sev == ErrorSeverity.LOW
        assert cat == "encoding_error"

    def test_memory_error_is_critical(self):
        from scripts.telegram.config import ErrorSeverity
        from scripts.telegram.error_handler import classify_error

        sev, cat = classify_error(MemoryError())
        assert sev == ErrorSeverity.CRITICAL
        assert cat == "memory_error"


class TestClassifyErrorMRO:
    """MRO 기반 상위 타입 탐색 검증."""

    def test_subclass_of_connection_error(self):
        """ConnectionResetError → ConnectionError의 서브클래스 → HIGH."""
        from scripts.telegram.config import ErrorSeverity
        from scripts.telegram.error_handler import classify_error

        sev, cat = classify_error(ConnectionResetError("reset"))
        assert sev == ErrorSeverity.HIGH
        assert cat == "connection_error"

    def test_unregistered_exception_returns_medium_unknown(self):
        """미등록 예외 → MEDIUM/unknown."""
        from scripts.telegram.config import ErrorSeverity
        from scripts.telegram.error_handler import classify_error

        class CustomError(Exception):
            pass

        sev, cat = classify_error(CustomError("custom"))
        assert sev == ErrorSeverity.MEDIUM
        assert cat == "unknown"

    def test_json_decode_error_maps_to_value_error(self):
        """json.JSONDecodeError → ValueError 서브클래스 → MEDIUM/value_error."""
        import json

        from scripts.telegram.config import ErrorSeverity
        from scripts.telegram.error_handler import classify_error

        try:
            json.loads("{{invalid")
        except json.JSONDecodeError as exc:
            sev, cat = classify_error(exc)
            assert sev == ErrorSeverity.MEDIUM
            assert cat == "value_error"


# ═══════════════════════════════════════════════════════════════
#  handle_error() flag ON/OFF 검증
# ═══════════════════════════════════════════════════════════════


class TestHandleError:
    """handle_error() 심각도별 구조화 로깅."""

    def test_flag_off_logs_warning(self, monkeypatch, caplog):
        """flag OFF → 단순 warning 로그."""
        monkeypatch.setattr(
            "scripts.telegram.config.FEATURE_FLAGS",
            {"error_classification": False},
        )
        from scripts.telegram.config import ErrorSeverity
        from scripts.telegram.error_handler import handle_error

        with caplog.at_level(logging.WARNING):
            handle_error(
                FileNotFoundError("test.txt"),
                ErrorSeverity.MEDIUM,
                "file_not_found",
                context={"task": "test"},
            )

        assert any("에러 발생" in r.message for r in caplog.records)

    def test_flag_on_critical_logs_critical(self, monkeypatch, caplog):
        """flag ON + CRITICAL → log.critical() 호출."""
        monkeypatch.setattr(
            "scripts.telegram.config.FEATURE_FLAGS",
            {"error_classification": True},
        )
        from scripts.telegram.config import ErrorSeverity
        from scripts.telegram.error_handler import handle_error

        with caplog.at_level(logging.DEBUG):
            handle_error(
                ImportError("missing_module"),
                ErrorSeverity.CRITICAL,
                "import_error",
                context={"module": "xyz"},
            )

        critical_records = [r for r in caplog.records if r.levelno == logging.CRITICAL]
        assert len(critical_records) >= 1
        assert "import_error" in critical_records[0].message

    def test_flag_on_low_logs_info(self, monkeypatch, caplog):
        """flag ON + LOW → log.info() 호출."""
        monkeypatch.setattr(
            "scripts.telegram.config.FEATURE_FLAGS",
            {"error_classification": True},
        )
        from scripts.telegram.config import ErrorSeverity
        from scripts.telegram.error_handler import handle_error

        with caplog.at_level(logging.DEBUG):
            handle_error(
                UnicodeEncodeError("utf-8", "", 0, 1, "test"),
                ErrorSeverity.LOW,
                "encoding_error",
            )

        info_records = [r for r in caplog.records if r.levelno == logging.INFO]
        assert len(info_records) >= 1
        assert "encoding_error" in info_records[0].message

    def test_no_context_still_works(self, monkeypatch, caplog):
        """context=None → 정상 동작."""
        monkeypatch.setattr(
            "scripts.telegram.config.FEATURE_FLAGS",
            {"error_classification": True},
        )
        from scripts.telegram.config import ErrorSeverity
        from scripts.telegram.error_handler import handle_error

        with caplog.at_level(logging.DEBUG):
            handle_error(
                ValueError("bad value"),
                ErrorSeverity.MEDIUM,
                "value_error",
                context=None,
            )

        warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warning_records) >= 1


# ═══════════════════════════════════════════════════════════════
#  통합 지점 존재 검증
# ═══════════════════════════════════════════════════════════════


class TestErrorHandlerIntegration:
    """소스코드에서 error_handler 통합 존재 검증."""

    def test_lazy_skill_has_classify_error(self):
        """telegram_executors._lazy_skill 내 classify_error 호출 존재."""
        import scripts.telegram.telegram_executors as mod

        src_path = mod.__file__
        with open(src_path, "r", encoding="utf-8") as f:
            source = f.read()

        assert "classify_error" in source
        assert "handle_error" in source

    def test_telegram_runner_has_classify_error(self):
        """telegram_runner.py 내 classify_error 호출 존재."""
        import scripts.telegram.telegram_runner as mod

        src_path = mod.__file__
        with open(src_path, "r", encoding="utf-8") as f:
            source = f.read()

        assert "classify_error" in source
        assert "handle_error" in source
