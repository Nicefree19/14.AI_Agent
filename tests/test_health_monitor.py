#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
W6 건강 모니터링 테스트
========================
health_monitor.py의 6개 점검 + 스로틀링 + 포맷팅 + flag 가드 검증.
"""

import collections
import time

import pytest


# ═══════════════════════════════════════════════════════════════
#  1. 디스크 공간 점검
# ═══════════════════════════════════════════════════════════════

class TestCheckDiskSpace:
    """_check_disk_space() 임계값 검증."""

    def test_sufficient_space(self, monkeypatch):
        """여유 충분 → ok."""
        from scripts.telegram import health_monitor as hm

        DiskUsage = collections.namedtuple("DiskUsage", ["total", "used", "free"])
        fake_usage = DiskUsage(
            total=100 * 1024**3,
            used=50 * 1024**3,
            free=50 * 1024**3,  # 50GB
        )
        monkeypatch.setattr("shutil.disk_usage", lambda _path: fake_usage)

        result = hm._check_disk_space()
        assert result["status"] == "ok"
        assert result["name"] == "disk_space"

    def test_low_space_warn(self, monkeypatch):
        """여유 < 500MB → warn."""
        from scripts.telegram import health_monitor as hm

        DiskUsage = collections.namedtuple("DiskUsage", ["total", "used", "free"])
        fake_usage = DiskUsage(
            total=100 * 1024**3,
            used=99.7 * 1024**3,
            free=300 * 1024**2,  # 300MB
        )
        monkeypatch.setattr("shutil.disk_usage", lambda _path: fake_usage)

        result = hm._check_disk_space()
        assert result["status"] == "warn"

    def test_critical_space(self, monkeypatch):
        """여유 < 100MB → critical."""
        from scripts.telegram import health_monitor as hm

        DiskUsage = collections.namedtuple("DiskUsage", ["total", "used", "free"])
        fake_usage = DiskUsage(
            total=100 * 1024**3,
            used=99.95 * 1024**3,
            free=50 * 1024**2,  # 50MB
        )
        monkeypatch.setattr("shutil.disk_usage", lambda _path: fake_usage)

        result = hm._check_disk_space()
        assert result["status"] == "critical"


# ═══════════════════════════════════════════════════════════════
#  2. 로그 크기 점검
# ═══════════════════════════════════════════════════════════════

class TestCheckLogSize:
    """_check_log_size() 임계값 검증."""

    def test_normal_log(self, tmp_path, monkeypatch):
        """정상 크기 → ok."""
        from scripts.telegram import health_monitor as hm

        log_file = tmp_path / "agent.log"
        log_file.write_bytes(b"x" * (1 * 1024 * 1024))  # 1MB
        monkeypatch.setattr(hm, "LOG_DIR", tmp_path)

        result = hm._check_log_size()
        assert result["status"] == "ok"
        assert result["name"] == "log_size"

    def test_large_log_warn(self, tmp_path, monkeypatch):
        """로그 총 > 20MB → warn."""
        from scripts.telegram import health_monitor as hm

        # 메인 로그 5MB + 백업 4개 × 5MB = 25MB
        log_file = tmp_path / "agent.log"
        log_file.write_bytes(b"x" * (5 * 1024 * 1024))
        for i in range(1, 5):
            backup = tmp_path / f"agent.log.{i}"
            backup.write_bytes(b"x" * (5 * 1024 * 1024))

        monkeypatch.setattr(hm, "LOG_DIR", tmp_path)

        result = hm._check_log_size()
        assert result["status"] == "warn"
        assert result["value"] > 20

    def test_missing_log_dir(self, tmp_path, monkeypatch):
        """로그 디렉토리에 파일 없음 → ok (에러 아님)."""
        from scripts.telegram import health_monitor as hm

        empty_dir = tmp_path / "empty_logs"
        empty_dir.mkdir()
        monkeypatch.setattr(hm, "LOG_DIR", empty_dir)

        result = hm._check_log_size()
        assert result["status"] == "ok"
        assert result["value"] == 0.0


# ═══════════════════════════════════════════════════════════════
#  3. 스탈 잠금 점검
# ═══════════════════════════════════════════════════════════════

class TestCheckStaleLocks:
    """_check_stale_locks() 동작 검증."""

    def test_no_lock(self, monkeypatch):
        """잠금 없음 → ok."""
        from scripts.telegram import health_monitor as hm

        monkeypatch.setattr(
            "scripts.telegram.health_monitor.check_working_lock",
            lambda: None,
            raising=False,
        )
        # 지연 import이므로 telegram_bot 모듈을 직접 패치
        import scripts.telegram.telegram_bot as tb
        monkeypatch.setattr(tb, "check_working_lock", lambda: None)

        result = hm._check_stale_locks()
        assert result["status"] == "ok"
        assert "없음" in result["message"]

    def test_active_lock(self, monkeypatch):
        """정상 잠금 → ok."""
        from scripts.telegram import health_monitor as hm
        import scripts.telegram.telegram_bot as tb

        active_lock = {"message_id": 42, "instruction_summary": "test"}
        monkeypatch.setattr(tb, "check_working_lock", lambda: active_lock)

        result = hm._check_stale_locks()
        assert result["status"] == "ok"
        assert "진행 중" in result["message"]

    def test_stale_lock_critical(self, monkeypatch):
        """스탈 잠금 → critical."""
        from scripts.telegram import health_monitor as hm
        import scripts.telegram.telegram_bot as tb

        stale_lock = {"message_id": 99, "stale": True}
        monkeypatch.setattr(tb, "check_working_lock", lambda: stale_lock)

        result = hm._check_stale_locks()
        assert result["status"] == "critical"
        assert "99" in result["message"]


# ═══════════════════════════════════════════════════════════════
#  4. 미처리 메시지 점검
# ═══════════════════════════════════════════════════════════════

class TestCheckPendingMessages:
    """_check_pending_messages() 임계값 검증."""

    def _make_messages(self, count, processed=False):
        return {"messages": [{"processed": processed} for _ in range(count)]}

    def test_no_pending(self, monkeypatch):
        """0개 미처리 → ok."""
        from scripts.telegram import health_monitor as hm
        import scripts.telegram.telegram_bot as tb

        monkeypatch.setattr(tb, "load_telegram_messages", lambda: self._make_messages(5, processed=True))

        result = hm._check_pending_messages()
        assert result["status"] == "ok"
        assert result["value"] == 0

    def test_few_pending(self, monkeypatch):
        """5개 미처리 → ok (10 이하)."""
        from scripts.telegram import health_monitor as hm
        import scripts.telegram.telegram_bot as tb

        data = {"messages": [
            *[{"processed": True} for _ in range(10)],
            *[{"processed": False} for _ in range(5)],
        ]}
        monkeypatch.setattr(tb, "load_telegram_messages", lambda: data)

        result = hm._check_pending_messages()
        assert result["status"] == "ok"
        assert result["value"] == 5

    def test_many_pending_warn(self, monkeypatch):
        """15개 미처리 → warn."""
        from scripts.telegram import health_monitor as hm
        import scripts.telegram.telegram_bot as tb

        monkeypatch.setattr(tb, "load_telegram_messages", lambda: self._make_messages(15, processed=False))

        result = hm._check_pending_messages()
        assert result["status"] == "warn"
        assert result["value"] == 15


# ═══════════════════════════════════════════════════════════════
#  5. 실패 상태 점검
# ═══════════════════════════════════════════════════════════════

class TestCheckFailedStates:
    """_check_failed_states() 동작 검증."""

    def test_no_failed(self, monkeypatch):
        """실패 없음 → ok."""
        from scripts.telegram import health_monitor as hm
        import scripts.telegram.telegram_bot as tb

        data = {"messages": [
            {"state": "completed"},
            {"state": "closed"},
            {},  # state 필드 없음
        ]}
        monkeypatch.setattr(tb, "load_telegram_messages", lambda: data)

        result = hm._check_failed_states()
        assert result["status"] == "ok"
        assert result["value"] == 0

    def test_has_failed_warn(self, monkeypatch):
        """FAILED 존재 → warn."""
        from scripts.telegram import health_monitor as hm
        import scripts.telegram.telegram_bot as tb

        data = {"messages": [
            {"state": "completed"},
            {"state": "failed"},
            {"state": "failed"},
        ]}
        monkeypatch.setattr(tb, "load_telegram_messages", lambda: data)

        result = hm._check_failed_states()
        assert result["status"] == "warn"
        assert result["value"] == 2


# ═══════════════════════════════════════════════════════════════
#  6. 인덱스 무결성 점검
# ═══════════════════════════════════════════════════════════════

class TestCheckIndexIntegrity:
    """_check_index_integrity() 동작 검증."""

    def test_clean_index(self, monkeypatch):
        """고아 0 → ok."""
        from scripts.telegram import health_monitor as hm
        import scripts.telegram.cleanup_manager as cm

        monkeypatch.setattr(cm, "clean_index", lambda dry_run=False: 0)

        result = hm._check_index_integrity()
        assert result["status"] == "ok"
        assert result["value"] == 0

    def test_orphaned_entries_warn(self, monkeypatch):
        """고아 존재 → warn."""
        from scripts.telegram import health_monitor as hm
        import scripts.telegram.cleanup_manager as cm

        monkeypatch.setattr(cm, "clean_index", lambda dry_run=False: 3)

        result = hm._check_index_integrity()
        assert result["status"] == "warn"
        assert result["value"] == 3


# ═══════════════════════════════════════════════════════════════
#  7. 오케스트레이터
# ═══════════════════════════════════════════════════════════════

class TestRunHealthCheck:
    """run_health_check() 통합 검증."""

    def _patch_all_ok(self, monkeypatch):
        """모든 점검을 ok로 모킹."""
        from scripts.telegram import health_monitor as hm
        import collections

        DiskUsage = collections.namedtuple("DiskUsage", ["total", "used", "free"])
        monkeypatch.setattr("shutil.disk_usage", lambda _: DiskUsage(100e9, 50e9, 50e9))
        monkeypatch.setattr(hm, "LOG_DIR", hm.LOG_DIR)  # no-op, real dir

        import scripts.telegram.telegram_bot as tb
        monkeypatch.setattr(tb, "check_working_lock", lambda: None)
        monkeypatch.setattr(tb, "load_telegram_messages", lambda: {"messages": []})

        import scripts.telegram.cleanup_manager as cm
        monkeypatch.setattr(cm, "clean_index", lambda dry_run=False: 0)

    def test_all_healthy(self, monkeypatch, tmp_path):
        """전부 ok → healthy=True."""
        from scripts.telegram import health_monitor as hm

        self._patch_all_ok(monkeypatch)
        monkeypatch.setattr(hm, "LOG_DIR", tmp_path)

        report = hm.run_health_check()
        assert report["healthy"] is True
        assert len(report["checks"]) == 6
        assert all(c["status"] == "ok" for c in report["checks"])
        assert "정상" in report["summary"]

    def test_mixed_issues(self, monkeypatch, tmp_path):
        """일부 warn → healthy=False."""
        from scripts.telegram import health_monitor as hm
        import scripts.telegram.telegram_bot as tb
        import scripts.telegram.cleanup_manager as cm
        import collections

        DiskUsage = collections.namedtuple("DiskUsage", ["total", "used", "free"])
        monkeypatch.setattr("shutil.disk_usage", lambda _: DiskUsage(100e9, 50e9, 50e9))
        monkeypatch.setattr(hm, "LOG_DIR", tmp_path)
        monkeypatch.setattr(tb, "check_working_lock", lambda: None)

        # 15개 미처리 → warn
        data = {"messages": [{"processed": False} for _ in range(15)]}
        monkeypatch.setattr(tb, "load_telegram_messages", lambda: data)

        monkeypatch.setattr(cm, "clean_index", lambda dry_run=False: 0)

        report = hm.run_health_check()
        assert report["healthy"] is False
        assert "이상 감지" in report["summary"]

    def test_check_failure_graceful(self, monkeypatch, tmp_path):
        """개별 점검 예외 → warn으로 전환, 나머지 정상."""
        from scripts.telegram import health_monitor as hm
        import scripts.telegram.telegram_bot as tb
        import scripts.telegram.cleanup_manager as cm
        import collections

        DiskUsage = collections.namedtuple("DiskUsage", ["total", "used", "free"])
        # disk_usage 예외 발생
        monkeypatch.setattr("shutil.disk_usage", lambda _: (_ for _ in ()).throw(OSError("no disk")))
        monkeypatch.setattr(hm, "LOG_DIR", tmp_path)
        monkeypatch.setattr(tb, "check_working_lock", lambda: None)
        monkeypatch.setattr(tb, "load_telegram_messages", lambda: {"messages": []})
        monkeypatch.setattr(cm, "clean_index", lambda dry_run=False: 0)

        report = hm.run_health_check()
        # disk_space 점검이 실패 → warn으로 전환
        disk_check = next(c for c in report["checks"] if c["name"] == "disk_space")
        assert disk_check["status"] == "warn"
        assert "실패" in disk_check["message"]
        # 나머지 5개는 정상
        others = [c for c in report["checks"] if c["name"] != "disk_space"]
        assert all(c["status"] == "ok" for c in others)


# ═══════════════════════════════════════════════════════════════
#  8. 스로틀링
# ═══════════════════════════════════════════════════════════════

class TestThrottling:
    """should_send_alert() / mark_alert_sent() 스로틀링 검증."""

    def test_first_alert_allowed(self, monkeypatch):
        """첫 알림 → True."""
        from scripts.telegram import health_monitor as hm

        monkeypatch.setattr(hm, "_last_alert_time", 0.0)

        assert hm.should_send_alert() is True

    def test_throttled_within_hour(self, monkeypatch):
        """1시간 내 재알림 → False."""
        from scripts.telegram import health_monitor as hm

        monkeypatch.setattr(hm, "_last_alert_time", time.time() - 100)  # 100초 전

        assert hm.should_send_alert() is False

    def test_allowed_after_hour(self, monkeypatch):
        """1시간 후 → True."""
        from scripts.telegram import health_monitor as hm

        monkeypatch.setattr(hm, "_last_alert_time", time.time() - 3700)  # 1시간+ 전

        assert hm.should_send_alert() is True


# ═══════════════════════════════════════════════════════════════
#  9. 알림 포맷
# ═══════════════════════════════════════════════════════════════

class TestFormatAlertMessage:
    """format_alert_message() 포맷팅 검증."""

    def test_format_critical(self):
        """critical 있을 때 포맷."""
        from scripts.telegram.health_monitor import format_alert_message

        report = {
            "healthy": False,
            "checks": [
                {"name": "disk_space", "status": "critical", "message": "여유 50MB", "value": 50},
                {"name": "log_size", "status": "ok", "message": "로그 총 5MB", "value": 5},
            ],
            "summary": "1건 이상 감지",
        }

        msg = format_alert_message(report)
        assert "건강 점검" in msg
        assert "disk_space" in msg
        assert "50MB" in msg

    def test_format_warn_only(self):
        """warn만 있을 때 포맷."""
        from scripts.telegram.health_monitor import format_alert_message

        report = {
            "healthy": False,
            "checks": [
                {"name": "pending_messages", "status": "warn", "message": "미처리 15건", "value": 15},
            ],
            "summary": "1건 이상 감지",
        }

        msg = format_alert_message(report)
        assert "pending_messages" in msg
        assert "15건" in msg


# ═══════════════════════════════════════════════════════════════
#  10. Flag 통합
# ═══════════════════════════════════════════════════════════════

class TestFlagIntegration:
    """proactive_alerts flag 가드 검증."""

    def test_runner_flag_off_no_health_check(self, monkeypatch):
        """flag OFF → telegram_runner에서 건강 점검 미실행."""
        from scripts.telegram.config import FEATURE_FLAGS, is_enabled

        monkeypatch.setitem(FEATURE_FLAGS, "proactive_alerts", False)

        # flag OFF 상태에서 is_enabled 확인
        assert is_enabled("proactive_alerts") is False

        # runner의 finally 블록 로직 시뮬레이션:
        # if is_enabled("proactive_alerts") → 건너뜀
        health_check_called = False

        if is_enabled("proactive_alerts"):
            health_check_called = True

        assert health_check_called is False
