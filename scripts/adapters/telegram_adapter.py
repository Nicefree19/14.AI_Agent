#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram Adapter for message_daemon (Layer A).

Reads from telegram_data/telegram_messages.json (written by Layer B).
Does NOT call Telegram API directly — avoids dual polling conflict.

Architecture:
    Layer B (scripts/telegram/telegram_runner.py):
        Active Telegram polling → saves to telegram_messages.json
    Layer A (this file):
        Passive reader → reads JSON → converts to UnifiedMessage → Obsidian Vault
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from .base import MessageAdapter, UnifiedMessage

log = logging.getLogger(__name__)

# telegram_data/ 기본 경로 (프로젝트 루트 기준)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_DATA_DIR = _PROJECT_ROOT / "telegram_data"


class TelegramAdapter(MessageAdapter):
    """
    Telegram message adapter for message_daemon.

    Layer A — 패시브 어댑터:
    - telegram_data/telegram_messages.json에서 신규 메시지 읽기
    - Telegram API 호출 없음 (Layer B가 담당)
    - UnifiedMessage로 변환하여 Obsidian Vault에 저장
    """

    adapter_name = "telegram"
    source_type = "chat"
    supports_watch = False
    poll_interval = 5  # minutes

    def __init__(self, config: Optional[dict] = None):
        super().__init__(config)
        self._data_dir: Optional[Path] = None
        self._messages_file: Optional[Path] = None
        self._last_read_file: Optional[Path] = None
        self._last_read_id: int = 0

    def initialize(self) -> bool:
        """
        어댑터 초기화.

        telegram_data/ 디렉토리와 telegram_messages.json 파일 확인.
        Layer B가 아직 실행되지 않았으면 graceful skip.
        """
        try:
            data_dir_str = self.config.get("data_dir", str(_DEFAULT_DATA_DIR))
            self._data_dir = Path(data_dir_str)

            # 절대 경로가 아니면 프로젝트 루트 기준
            if not self._data_dir.is_absolute():
                self._data_dir = _PROJECT_ROOT / self._data_dir

            self._messages_file = self._data_dir / "telegram_messages.json"
            self._last_read_file = self._data_dir / "last_read_id.json"

            # 디렉토리 존재 확인 (없으면 생성 — Layer B가 아직 안 돌았을 수 있음)
            self._data_dir.mkdir(parents=True, exist_ok=True)

            # 마지막 읽기 위치 복원
            self._last_read_id = self._load_last_read_id()

            self._initialized = True
            log.info(
                f"TelegramAdapter initialized: data_dir={self._data_dir}, "
                f"last_read_id={self._last_read_id}"
            )
            return True

        except Exception as e:
            log.error(f"TelegramAdapter initialization failed: {e}")
            return False

    def fetch(self, limit: int = 50, **kwargs) -> List[UnifiedMessage]:
        """
        telegram_messages.json에서 신규 메시지 읽기.

        Layer B (telegram_runner)가 저장한 JSON 파일에서 읽기만 함.
        Telegram API 호출 없음.

        Args:
            limit: 최대 메시지 수
            **kwargs: 추가 옵션

        Returns:
            List[UnifiedMessage]: 새 메시지 목록
        """
        if not self._initialized:
            log.warning("TelegramAdapter not initialized")
            return []

        if not self._messages_file or not self._messages_file.exists():
            log.debug("telegram_messages.json not found — Layer B may not be running")
            return []

        try:
            with open(self._messages_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            all_messages = data.get("messages", [])

            # 마지막 읽기 이후의 새 메시지만 필터링
            # bot 메시지(type=="bot") 및 비정수 message_id 안전 스킵
            new_messages = []
            for m in all_messages:
                if m.get("type") == "bot":
                    continue
                mid = m.get("message_id", 0)
                if not isinstance(mid, int):
                    continue
                if mid > self._last_read_id:
                    new_messages.append(m)

            # limit 적용
            if len(new_messages) > limit:
                new_messages = new_messages[:limit]

            if not new_messages:
                return []

            # UnifiedMessage로 변환
            unified = []
            for msg in new_messages:
                try:
                    um = self._to_unified(msg)
                    unified.append(um)
                except Exception as e:
                    log.warning(f"Failed to convert message {msg.get('message_id')}: {e}")
                    continue

            # 마지막 읽기 위치 갱신 — int ID만 대상
            if unified:
                int_ids = [
                    m.get("message_id") for m in new_messages
                    if isinstance(m.get("message_id"), int)
                ]
                if int_ids:
                    max_id = max(int_ids)
                    self._last_read_id = max_id
                    self._save_last_read_id()
                    log.info(f"TelegramAdapter fetched {len(unified)} new messages (last_id={max_id})")

            return unified

        except json.JSONDecodeError as e:
            log.error(f"telegram_messages.json parse error: {e}")
            return []
        except Exception as e:
            log.error(f"TelegramAdapter fetch error: {e}")
            return []

    def _to_unified(self, msg: dict) -> UnifiedMessage:
        """
        텔레그램 메시지 → UnifiedMessage 변환.

        Args:
            msg: telegram_messages.json의 단일 메시지 dict

        Returns:
            UnifiedMessage 인스턴스
        """
        message_id = msg.get("message_id", 0)
        text = msg.get("text", "")
        sender_name = msg.get("first_name", "")
        if msg.get("last_name"):
            sender_name += f" {msg['last_name']}"
        username = msg.get("username", "")

        # sender 형식: "이름 (@username)" 또는 "이름"
        sender = sender_name.strip()
        if username:
            sender = f"{sender} (@{username})"

        # timestamp 파싱
        ts_str = msg.get("timestamp", "")
        try:
            timestamp = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            timestamp = datetime.now()

        # subject 생성 (텍스트 앞부분 + 파일/위치 정보)
        subject_parts = []
        if text:
            subject_parts.append(text[:50])
        if msg.get("files"):
            subject_parts.append(f"+{len(msg['files'])} files")
        if msg.get("location"):
            subject_parts.append("+location")
        subject = " ".join(subject_parts) if subject_parts else "Telegram message"

        # raw_metadata에 추가 정보 보존
        metadata = {
            "chat_id": msg.get("chat_id"),
            "user_id": msg.get("user_id"),
            "message_id": message_id,
            "files": msg.get("files", []),
            "location": msg.get("location"),
            "processed": msg.get("processed", False),
        }

        return UnifiedMessage(
            id=f"telegram_{message_id}",
            source_type="chat",
            source_adapter="telegram",
            sender=sender,
            subject=subject,
            body=text,
            timestamp=timestamp,
            raw_metadata=metadata,
        )

    def _load_last_read_id(self) -> int:
        """마지막 읽기 위치 복원."""
        if not self._last_read_file or not self._last_read_file.exists():
            return 0
        try:
            with open(self._last_read_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("last_read_id", 0)
        except Exception:
            return 0

    def _save_last_read_id(self):
        """마지막 읽기 위치 저장."""
        if not self._last_read_file:
            return
        try:
            with open(self._last_read_file, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "last_read_id": self._last_read_id,
                        "updated_at": datetime.now().isoformat(),
                    },
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
        except Exception as e:
            log.warning(f"Failed to save last_read_id: {e}")

    def get_status(self) -> dict:
        """어댑터 상태 정보 반환."""
        base = super().get_status()
        base.update({
            "data_dir": str(self._data_dir) if self._data_dir else None,
            "messages_file_exists": (
                self._messages_file.exists() if self._messages_file else False
            ),
            "last_read_id": self._last_read_id,
        })
        return base

    def close(self):
        """리소스 정리 (Layer A는 파일 읽기만 하므로 특별한 정리 불필요)."""
        self._save_last_read_id()
        super().close()
