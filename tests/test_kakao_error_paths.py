#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
W4: 카카오톡 에러 경로 테스트

- 카카오 예외의 에러 분류 정확성
- _preflight() flag ON/OFF 동작
- _verify_kakaotalk_running() flag ON/OFF 동작
- 타임아웃 상수 중앙화 검증
- 답장 대기 상태 수명 주기
- 소스코드 통합 지점 존재 검증
"""

import json
import subprocess
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest


# ═══════════════════════════════════════════════════════════════
#  클래스 1: 카카오 예외 분류 검증
# ═══════════════════════════════════════════════════════════════


class TestKakaoExceptionClassify:
    """카카오톡 예외가 _ERROR_MAP에 올바르게 등록되었는지 검증."""

    def test_kakao_not_running_is_high(self):
        from scripts.telegram.config import ErrorSeverity
        from scripts.telegram.error_handler import classify_error
        from scripts.telegram.kakao_pywinauto import KakaoNotRunningError

        sev, cat = classify_error(KakaoNotRunningError("test"))
        assert sev == ErrorSeverity.HIGH
        assert cat == "kakao_not_running"

    def test_kakao_activation_error_is_medium(self):
        from scripts.telegram.config import ErrorSeverity
        from scripts.telegram.error_handler import classify_error
        from scripts.telegram.kakao_pywinauto import KakaoActivationError

        sev, cat = classify_error(KakaoActivationError("test"))
        assert sev == ErrorSeverity.MEDIUM
        assert cat == "kakao_activation_failed"

    def test_plain_runtime_error_maps_via_mro(self):
        """일반 RuntimeError → MRO 탐색 → HIGH/runtime_error."""
        from scripts.telegram.config import ErrorSeverity
        from scripts.telegram.error_handler import classify_error

        sev, cat = classify_error(RuntimeError("generic"))
        assert sev == ErrorSeverity.HIGH
        assert cat == "runtime_error"


# ═══════════════════════════════════════════════════════════════
#  클래스 2: _preflight() flag 동작 검증
# ═══════════════════════════════════════════════════════════════


class TestKakaoPreflight:
    """_preflight() flag ON/OFF 동작 검증."""

    def _mock_subprocess_not_running(self, *args, **kwargs):
        """KakaoTalk NOT_RUNNING 시뮬레이션."""
        result = subprocess.CompletedProcess(
            args=args, returncode=0, stdout="NOT_RUNNING", stderr=""
        )
        return result

    def _mock_subprocess_running(self, *args, **kwargs):
        """KakaoTalk RUNNING 시뮬레이션."""
        result = subprocess.CompletedProcess(
            args=args, returncode=0, stdout="RUNNING", stderr=""
        )
        return result

    def _mock_subprocess_timeout(self, *args, **kwargs):
        """subprocess 타임아웃 시뮬레이션."""
        raise subprocess.TimeoutExpired(cmd="powershell", timeout=5)

    def test_flag_off_timeout_passes_silently(self, monkeypatch):
        """flag OFF + 타임아웃 → 조용히 pass (기존 동작)."""
        monkeypatch.setattr(
            "scripts.telegram.config.FEATURE_FLAGS",
            {"kakao_preflight": False},
        )
        from scripts.telegram.kakao_pywinauto import _preflight

        with patch("subprocess.run", side_effect=self._mock_subprocess_timeout):
            # 예외 발생하지 않아야 함
            _preflight()

    def test_flag_on_timeout_raises(self, monkeypatch):
        """flag ON + 타임아웃 → KakaoNotRunningError raise."""
        monkeypatch.setattr(
            "scripts.telegram.config.FEATURE_FLAGS",
            {"kakao_preflight": True},
        )
        from scripts.telegram.kakao_pywinauto import (
            KakaoNotRunningError,
            _preflight,
        )

        with patch("subprocess.run", side_effect=self._mock_subprocess_timeout):
            with pytest.raises(KakaoNotRunningError, match="타임아웃"):
                _preflight()

    def test_flag_on_generic_exception_raises(self, monkeypatch):
        """flag ON + 일반 예외 → KakaoNotRunningError raise."""
        monkeypatch.setattr(
            "scripts.telegram.config.FEATURE_FLAGS",
            {"kakao_preflight": True},
        )
        from scripts.telegram.kakao_pywinauto import (
            KakaoNotRunningError,
            _preflight,
        )

        with patch("subprocess.run", side_effect=OSError("test error")):
            with pytest.raises(KakaoNotRunningError, match="프리플라이트 실패"):
                _preflight()

    def test_flag_on_running_no_error(self, monkeypatch):
        """flag ON + 정상 실행 → 에러 없음."""
        monkeypatch.setattr(
            "scripts.telegram.config.FEATURE_FLAGS",
            {"kakao_preflight": True},
        )
        from scripts.telegram.kakao_pywinauto import _preflight

        with patch("subprocess.run", side_effect=self._mock_subprocess_running):
            _preflight()  # 정상 통과

    def test_not_running_always_raises(self, monkeypatch):
        """flag 무관 + NOT_RUNNING → 항상 KakaoNotRunningError."""
        monkeypatch.setattr(
            "scripts.telegram.config.FEATURE_FLAGS",
            {"kakao_preflight": False},
        )
        from scripts.telegram.kakao_pywinauto import (
            KakaoNotRunningError,
            _preflight,
        )

        with patch("subprocess.run", side_effect=self._mock_subprocess_not_running):
            with pytest.raises(KakaoNotRunningError):
                _preflight()


# ═══════════════════════════════════════════════════════════════
#  클래스 3: _verify_kakaotalk_running() flag 동작 검증
# ═══════════════════════════════════════════════════════════════


class TestVerifyKakaotalkRunning:
    """_verify_kakaotalk_running() flag ON/OFF 동작 검증."""

    def test_flag_off_exception_returns_true(self, monkeypatch):
        """flag OFF + 예외 → return True (기존 fail-open)."""
        monkeypatch.setattr(
            "scripts.telegram.config.FEATURE_FLAGS",
            {"kakao_preflight": False},
        )
        from scripts.telegram.kakao_desktop import _verify_kakaotalk_running

        with patch("subprocess.run", side_effect=OSError("test")):
            assert _verify_kakaotalk_running() is True

    def test_flag_on_exception_returns_false(self, monkeypatch):
        """flag ON + 예외 → return False (fail-closed)."""
        monkeypatch.setattr(
            "scripts.telegram.config.FEATURE_FLAGS",
            {"kakao_preflight": True},
        )
        from scripts.telegram.kakao_desktop import _verify_kakaotalk_running

        with patch("subprocess.run", side_effect=OSError("test")):
            assert _verify_kakaotalk_running() is False

    def test_running_process_returns_true(self, monkeypatch):
        """프로세스 실행 중 → return True."""
        from scripts.telegram.kakao_desktop import _verify_kakaotalk_running

        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="RUNNING", stderr=""
        )
        with patch("scripts.telegram.kakao_desktop.subprocess.run", return_value=mock_result):
            assert _verify_kakaotalk_running() is True

    def test_not_running_returns_false(self, monkeypatch):
        """프로세스 미실행 → return False."""
        from scripts.telegram.kakao_desktop import _verify_kakaotalk_running

        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="NOT_RUNNING", stderr=""
        )
        with patch("scripts.telegram.kakao_desktop.subprocess.run", return_value=mock_result):
            assert _verify_kakaotalk_running() is False


# ═══════════════════════════════════════════════════════════════
#  클래스 4: 타임아웃 상수 중앙화 검증
# ═══════════════════════════════════════════════════════════════


class TestTimeoutConstants:
    """config.py의 카카오 타임아웃 상수 검증."""

    def test_clipboard_wait_sec(self):
        from scripts.telegram.config import KAKAO_CLIPBOARD_WAIT_SEC

        assert KAKAO_CLIPBOARD_WAIT_SEC == 15

    def test_ps_timeout_sec(self):
        from scripts.telegram.config import KAKAO_PS_TIMEOUT_SEC

        assert KAKAO_PS_TIMEOUT_SEC == 5

    def test_pending_reply_timeout_min(self):
        from scripts.telegram.config import PENDING_REPLY_TIMEOUT_MIN

        assert PENDING_REPLY_TIMEOUT_MIN == 10

    def test_no_local_pending_reply_in_desktop(self):
        """kakao_desktop.py에 PENDING_REPLY_TIMEOUT_MIN 로컬 정의 없음."""
        import re

        import scripts.telegram.kakao_desktop as mod

        src_path = mod.__file__
        with open(src_path, "r", encoding="utf-8") as f:
            source = f.read()

        # config에서 import한 라인은 있어야 함
        assert "from scripts.telegram.config import" in source
        assert "PENDING_REPLY_TIMEOUT_MIN" in source

        # 로컬 할당 (예: PENDING_REPLY_TIMEOUT_MIN = 10) 패턴 검출
        # 주의: 함수 인자 내 사용 (minutes=PENDING_REPLY_TIMEOUT_MIN)은 제외
        local_assign = re.compile(
            r"^\s*PENDING_REPLY_TIMEOUT_MIN\s*=",
            re.MULTILINE,
        )
        matches = local_assign.findall(source)
        assert len(matches) == 0, (
            f"kakao_desktop.py에 로컬 정의 발견: {matches}"
        )


# ═══════════════════════════════════════════════════════════════
#  클래스 5: 답장 대기 상태 수명 주기 검증
# ═══════════════════════════════════════════════════════════════


class TestPendingReplyExpiry:
    """답장 대기 상태 저장/로드/만료/삭제 검증."""

    @pytest.fixture(autouse=True)
    def _setup_temp_pending(self, tmp_path, monkeypatch):
        """임시 답장 대기 파일로 격리."""
        self.pending_file = tmp_path / "kakao_pending_reply.json"
        monkeypatch.setattr(
            "scripts.telegram.kakao_desktop._PENDING_REPLY_FILE",
            self.pending_file,
        )

    def test_save_and_load_cycle(self):
        """save → load → 데이터 일치."""
        from scripts.telegram.kakao_desktop import (
            load_pending_reply,
            save_pending_reply,
        )

        save_pending_reply(
            chat_room="테스트방",
            reply_text="안녕하세요",
            chat_id=1234,
            task_dir="/tmp/test",
        )

        data = load_pending_reply()
        assert data is not None
        assert data["chat_room"] == "테스트방"
        assert data["reply_text"] == "안녕하세요"
        assert data["status"] == "pending_confirmation"

    def test_load_returns_none_when_no_file(self):
        """파일 없음 → None."""
        from scripts.telegram.kakao_desktop import load_pending_reply

        assert load_pending_reply() is None

    def test_expired_reply_returns_none(self):
        """만료된 답장 → None (자동 삭제)."""
        from scripts.telegram.kakao_desktop import load_pending_reply

        # 이미 만료된 데이터 직접 작성
        expired_data = {
            "chat_room": "테스트방",
            "reply_text": "만료됨",
            "status": "pending_confirmation",
            "created_at": (datetime.now() - timedelta(minutes=20)).isoformat(),
            "expires_at": (datetime.now() - timedelta(minutes=10)).isoformat(),
            "chat_id": 1234,
            "task_dir": "/tmp/test",
        }
        self.pending_file.write_text(
            json.dumps(expired_data, ensure_ascii=False), encoding="utf-8"
        )

        assert load_pending_reply() is None
        # 파일도 삭제되어야 함
        assert not self.pending_file.exists()

    def test_invalid_json_returns_none(self):
        """잘못된 JSON → None (에러 없이)."""
        from scripts.telegram.kakao_desktop import load_pending_reply

        self.pending_file.write_text("{invalid json", encoding="utf-8")
        assert load_pending_reply() is None

    def test_clear_removes_file(self):
        """clear → 파일 삭제."""
        from scripts.telegram.kakao_desktop import (
            clear_pending_reply,
            save_pending_reply,
        )

        save_pending_reply("방", "텍스트", 1234, "/tmp")
        assert self.pending_file.exists()

        clear_pending_reply()
        assert not self.pending_file.exists()

    def test_has_pending_reply_before_and_after_expiry(self):
        """만료 전 True, 만료 후 False."""
        from scripts.telegram.kakao_desktop import (
            has_pending_reply,
            save_pending_reply,
        )

        save_pending_reply("방", "텍스트", 1234, "/tmp")
        assert has_pending_reply() is True

        # 만료 시간을 과거로 조작
        data = json.loads(self.pending_file.read_text(encoding="utf-8"))
        data["expires_at"] = (datetime.now() - timedelta(minutes=1)).isoformat()
        self.pending_file.write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )
        assert has_pending_reply() is False


# ═══════════════════════════════════════════════════════════════
#  클래스 6: 소스코드 통합 지점 검증
# ═══════════════════════════════════════════════════════════════


class TestKakaoErrorHandlerIntegration:
    """소스코드에서 W4 통합 지점 존재 검증."""

    def test_pywinauto_has_is_enabled(self):
        """kakao_pywinauto.py에 is_enabled 호출 존재."""
        import scripts.telegram.kakao_pywinauto as mod

        with open(mod.__file__, "r", encoding="utf-8") as f:
            source = f.read()
        assert "is_enabled" in source

    def test_pywinauto_uses_config_timeout(self):
        """kakao_pywinauto.py에 KAKAO_PS_TIMEOUT_SEC 임포트 존재."""
        import scripts.telegram.kakao_pywinauto as mod

        with open(mod.__file__, "r", encoding="utf-8") as f:
            source = f.read()
        assert "KAKAO_PS_TIMEOUT_SEC" in source

    def test_pywinauto_uses_config_clipboard_wait(self):
        """kakao_pywinauto.py에 KAKAO_CLIPBOARD_WAIT_SEC 임포트 존재."""
        import scripts.telegram.kakao_pywinauto as mod

        with open(mod.__file__, "r", encoding="utf-8") as f:
            source = f.read()
        assert "KAKAO_CLIPBOARD_WAIT_SEC" in source

    def test_desktop_imports_pending_timeout(self):
        """kakao_desktop.py에 PENDING_REPLY_TIMEOUT_MIN import 존재."""
        import scripts.telegram.kakao_desktop as mod

        with open(mod.__file__, "r", encoding="utf-8") as f:
            source = f.read()
        assert "from scripts.telegram.config import" in source
        assert "PENDING_REPLY_TIMEOUT_MIN" in source

    def test_desktop_uses_config_timeout(self):
        """kakao_desktop.py에 KAKAO_PS_TIMEOUT_SEC 임포트 존재."""
        import scripts.telegram.kakao_desktop as mod

        with open(mod.__file__, "r", encoding="utf-8") as f:
            source = f.read()
        assert "KAKAO_PS_TIMEOUT_SEC" in source

    def test_error_handler_has_kakao_exceptions(self):
        """error_handler.py에 카카오 예외 등록 존재."""
        import scripts.telegram.error_handler as mod

        with open(mod.__file__, "r", encoding="utf-8") as f:
            source = f.read()
        assert "KakaoNotRunningError" in source
        assert "KakaoActivationError" in source
