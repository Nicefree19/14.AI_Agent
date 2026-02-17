#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
W3C: 메시지 상태 머신 테스트

- MessageState enum 7단계 검증
- _update_message_state() flag ON/OFF 동작
- 상태 전이 위치 존재 확인
- 하위호환성 (flag OFF 시 기존 동작 동일)
"""

import json
import os
import tempfile

import pytest


# ═══════════════════════════════════════════════════════════════
#  MessageState enum 검증
# ═══════════════════════════════════════════════════════════════


class TestMessageStateEnum:
    """MessageState enum 값 및 순서 검증."""

    def test_seven_states_exist(self):
        from scripts.telegram.telegram_bot import MessageState

        expected = {
            "PENDING", "TRIAGED", "CONTEXT_READY",
            "EXECUTING", "COMPLETED", "FAILED", "CLOSED",
        }
        actual = {s.name for s in MessageState}
        assert actual == expected, f"상태 불일치: {actual.symmetric_difference(expected)}"

    def test_state_values_are_lowercase(self):
        from scripts.telegram.telegram_bot import MessageState

        for state in MessageState:
            assert state.value == state.name.lower(), (
                f"{state.name} 값이 소문자가 아님: {state.value}"
            )

    def test_state_is_string_enum(self):
        from scripts.telegram.telegram_bot import MessageState

        # str(Enum) 비교 가능해야 함
        assert MessageState.PENDING == "pending"
        assert MessageState.CLOSED == "closed"


# ═══════════════════════════════════════════════════════════════
#  _update_message_state() 동작 검증
# ═══════════════════════════════════════════════════════════════


class TestUpdateMessageState:
    """_update_message_state() flag ON/OFF 동작 검증."""

    @pytest.fixture(autouse=True)
    def _setup_temp_messages(self, tmp_path, monkeypatch):
        """임시 메시지 파일로 격리."""
        self.msg_file = tmp_path / "telegram_messages.json"
        sample_messages = [
            {
                "message_id": 100,
                "text": "테스트 메시지",
                "chat_id": 1234,
                "timestamp": "2026-02-17 10:00:00",
                "first_name": "tester",
                "processed": False,
            },
            {
                "message_id": 101,
                "text": "두 번째 메시지",
                "chat_id": 1234,
                "timestamp": "2026-02-17 10:01:00",
                "first_name": "tester",
                "processed": False,
            },
        ]
        self.msg_file.write_text(json.dumps(sample_messages), encoding="utf-8")

        # telegram_bot 모듈의 MESSAGES_FILE을 임시 경로로 패치
        monkeypatch.setattr(
            "scripts.telegram.telegram_bot.MESSAGES_FILE",
            str(self.msg_file),
        )

    def test_flag_off_no_state_written(self, monkeypatch):
        """flag OFF → 상태 기록 없음 (no-op)."""
        monkeypatch.setattr(
            "scripts.telegram.config.FEATURE_FLAGS",
            {"state_machine": False},
        )
        from scripts.telegram.telegram_bot import (
            MessageState,
            _update_message_state,
        )

        _update_message_state(100, MessageState.EXECUTING)

        messages = json.loads(self.msg_file.read_text(encoding="utf-8"))
        msg100 = next(m for m in messages if m["message_id"] == 100)
        assert "state" not in msg100, "flag OFF인데 state 필드가 존재"

    def test_flag_on_state_written(self, monkeypatch):
        """flag ON → 상태 기록됨."""
        monkeypatch.setattr(
            "scripts.telegram.config.FEATURE_FLAGS",
            {"state_machine": True},
        )
        from scripts.telegram.telegram_bot import (
            MessageState,
            _update_message_state,
        )

        _update_message_state(100, MessageState.EXECUTING)

        messages = json.loads(self.msg_file.read_text(encoding="utf-8"))
        msg100 = next(m for m in messages if m["message_id"] == 100)
        assert msg100["state"] == "executing"
        assert "state_updated_at" in msg100

    def test_extra_recorded_in_history(self, monkeypatch):
        """extra 매개변수가 state_history에 기록됨."""
        monkeypatch.setattr(
            "scripts.telegram.config.FEATURE_FLAGS",
            {"state_machine": True},
        )
        from scripts.telegram.telegram_bot import (
            MessageState,
            _update_message_state,
        )

        _update_message_state(
            100, MessageState.FAILED,
            extra={"reason": "ConnectionError"},
        )

        messages = json.loads(self.msg_file.read_text(encoding="utf-8"))
        msg100 = next(m for m in messages if m["message_id"] == 100)
        assert msg100["state"] == "failed"
        history = msg100.get("state_history", [])
        assert len(history) == 1
        assert history[0]["state"] == "failed"
        assert history[0]["reason"] == "ConnectionError"

    def test_nonexistent_message_id_no_error(self, monkeypatch):
        """존재하지 않는 message_id → 조용히 무시."""
        monkeypatch.setattr(
            "scripts.telegram.config.FEATURE_FLAGS",
            {"state_machine": True},
        )
        from scripts.telegram.telegram_bot import (
            MessageState,
            _update_message_state,
        )

        # 999는 없는 ID → 예외 없이 통과
        _update_message_state(999, MessageState.TRIAGED)

    def test_sequential_state_transitions(self, monkeypatch):
        """연속 상태 전이: TRIAGED → CONTEXT_READY → EXECUTING → COMPLETED."""
        monkeypatch.setattr(
            "scripts.telegram.config.FEATURE_FLAGS",
            {"state_machine": True},
        )
        from scripts.telegram.telegram_bot import (
            MessageState,
            _update_message_state,
        )

        transitions = [
            MessageState.TRIAGED,
            MessageState.CONTEXT_READY,
            MessageState.EXECUTING,
            MessageState.COMPLETED,
        ]

        for state in transitions:
            _update_message_state(100, state)

        messages = json.loads(self.msg_file.read_text(encoding="utf-8"))
        msg100 = next(m for m in messages if m["message_id"] == 100)
        assert msg100["state"] == "completed"


# ═══════════════════════════════════════════════════════════════
#  상태 전이 통합 지점 존재 검증
# ═══════════════════════════════════════════════════════════════


class TestStateTransitionIntegration:
    """소스코드에서 상태 전이 호출 존재 검증."""

    @pytest.fixture(autouse=True)
    def _load_source(self):
        """telegram_bot.py 소스를 한 번만 읽기."""
        import scripts.telegram.telegram_bot as mod

        src_path = mod.__file__
        with open(src_path, "r", encoding="utf-8") as f:
            self.source = f.read()

    def test_triaged_in_check_telegram(self):
        """classify_message() 이후 TRIAGED 전이 존재."""
        assert "MessageState.TRIAGED" in self.source

    def test_context_ready_in_combine_tasks(self):
        """combine_tasks() 내 CONTEXT_READY 전이 존재."""
        assert "MessageState.CONTEXT_READY" in self.source

    def test_executing_in_create_working_lock(self):
        """create_working_lock() 내 EXECUTING 전이 존재."""
        assert "MessageState.EXECUTING" in self.source

    def test_completed_in_report_telegram(self):
        """report_telegram() 내 COMPLETED 전이 존재."""
        assert "MessageState.COMPLETED" in self.source

    def test_failed_in_report_telegram(self):
        """report_telegram() 내 FAILED 전이 존재."""
        assert "MessageState.FAILED" in self.source

    def test_closed_in_mark_done_telegram(self):
        """mark_done_telegram() 내 CLOSED 전이 존재."""
        assert "MessageState.CLOSED" in self.source
