#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
중앙 로깅 모듈
==============
RotatingFileHandler 기반. 파일 + 콘솔 동시 출력.

사용법:
    from scripts.telegram.logger import get_logger
    log = get_logger(__name__)
    log.info("작업 시작")
"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

from scripts.telegram.config import LOG_DIR, LOG_MAX_BYTES, LOG_BACKUP_COUNT

_initialized = False

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_LOG_DATE_FMT = "%Y-%m-%d %H:%M:%S"


def _setup_root_logger() -> None:
    """루트 로거에 파일 + 콘솔 핸들러 설정 (1회만)."""
    global _initialized
    if _initialized:
        return
    _initialized = True

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    fmt = logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATE_FMT)

    # 파일 핸들러 — 5 MB × 5 백업 = 최대 25 MB
    fh = logging.handlers.RotatingFileHandler(
        LOG_DIR / "agent.log",
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    # 콘솔 핸들러 — Claude Code 세션에서도 보이도록
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    root.addHandler(ch)


def get_logger(name: str) -> logging.Logger:
    """모듈별 로거 반환. 첫 호출 시 루트 핸들러 자동 설정."""
    _setup_root_logger()
    return logging.getLogger(name)


def safe_print(msg: str, *, fallback_logger_name: str = "safe_print") -> None:
    """cp949 콘솔에서도 안전한 print.

    1) print(msg) 시도
    2) UnicodeEncodeError → ASCII 안전 문자열로 재시도
    3) 그 외 예외 → 파일 로거로만 기록 (콘솔 출력 포기)
    """
    try:
        print(msg)
    except UnicodeEncodeError:
        try:
            print(msg.encode("ascii", errors="replace").decode("ascii"))
        except Exception:
            get_logger(fallback_logger_name).debug(
                "콘솔 출력 실패 (ASCII fallback도 실패): %s", msg[:200]
            )
    except Exception:
        get_logger(fallback_logger_name).debug(
            "콘솔 출력 실패: %s", msg[:200]
        )
