#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pytest 공통 설정 — sys.path + 공유 fixture.
"""

import os
import sys
import tempfile

import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# ═══════════════════════════════════════════════════════════════
#  공유 Fixture
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def mock_context():
    """모든 executor 단위 테스트용 표준 컨텍스트."""
    return {
        "combined": {
            "combined_instruction": "테스트 지시사항",
            "message_ids": [0],
            "chat_id": 0,
            "all_timestamps": ["2026-02-17 00:00:00"],
            "files": [],
        },
        "memories": [],
        "task_dir": tempfile.mkdtemp(),
        "send_progress": lambda x: None,
    }


@pytest.fixture
def feature_flags_off(monkeypatch):
    """모든 feature flag를 OFF로 강제."""
    from scripts.telegram.config import FEATURE_FLAGS

    for key in FEATURE_FLAGS:
        monkeypatch.setitem(FEATURE_FLAGS, key, False)


@pytest.fixture
def feature_flags_on(monkeypatch):
    """모든 feature flag를 ON으로 강제."""
    from scripts.telegram.config import FEATURE_FLAGS

    for key in FEATURE_FLAGS:
        monkeypatch.setitem(FEATURE_FLAGS, key, True)
