"""
p5_utils — P5 프로젝트 공통 유틸리티.

YAML 로딩, 마크다운 프론트매터 파싱, 로거 설정 등
여러 스크립트에서 반복되는 패턴을 통합한다.

Usage::

    from p5_utils import load_yaml, parse_frontmatter, setup_logger
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import yaml


# ── YAML / Config ────────────────────────────────────────

def load_yaml(path: str | Path, default: Any = None) -> Any:
    """YAML 파일 로드. 실패 시 *default* 반환.

    Args:
        path: YAML 파일 경로
        default: 파일 없음/파싱 실패 시 반환값 (``None`` 이면 ``{}``)

    Returns:
        파싱된 데이터 또는 *default*
    """
    if default is None:
        default = {}
    path = Path(path)
    if not path.exists():
        logging.debug("YAML file not found: %s", path)
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data if data is not None else default
    except yaml.YAMLError as e:
        logging.warning("YAML parse error (%s): %s", path.name, e)
        return default
    except OSError as e:
        logging.warning("YAML read error (%s): %s", path.name, e)
        return default


# ── Frontmatter ──────────────────────────────────────────

def parse_frontmatter(file_path: str | Path) -> Dict[str, Any]:
    """마크다운 파일에서 YAML 프론트매터를 파싱.

    파일이 ``---`` 로 시작하고 두 번째 ``---`` 가 있을 때만 파싱한다.
    프론트매터가 없거나 파싱 실패 시 빈 dict 반환.

    Args:
        file_path: 마크다운(.md) 파일 경로

    Returns:
        프론트매터 dict, 또는 ``{}``
    """
    file_path = Path(file_path)
    if not file_path.exists():
        return {}
    try:
        content = file_path.read_text(encoding="utf-8")
        if not content.startswith("---"):
            return {}
        parts = content.split("---", 2)
        if len(parts) < 3:
            return {}
        fm = yaml.safe_load(parts[1])
        return fm if isinstance(fm, dict) else {}
    except yaml.YAMLError as e:
        logging.debug("Frontmatter parse error (%s): %s", file_path.name, e)
        return {}
    except OSError as e:
        logging.debug("Frontmatter read error (%s): %s", file_path.name, e)
        return {}


def frontmatter_and_body(file_path: str | Path) -> tuple[Dict[str, Any], str]:
    """프론트매터 + 본문을 동시에 반환.

    Returns:
        (frontmatter_dict, body_text) 튜플.
        프론트매터 없으면 ({}, 전체내용).
    """
    file_path = Path(file_path)
    if not file_path.exists():
        return {}, ""
    try:
        content = file_path.read_text(encoding="utf-8")
        if not content.startswith("---"):
            return {}, content
        parts = content.split("---", 2)
        if len(parts) < 3:
            return {}, content
        fm = yaml.safe_load(parts[1])
        fm = fm if isinstance(fm, dict) else {}
        return fm, parts[2]
    except Exception:
        return {}, ""


# ── Logging ──────────────────────────────────────────────

def setup_logger(
    name: str,
    log_file: Optional[str | Path] = None,
    level: int = logging.INFO,
) -> logging.Logger:
    """로거 생성: 콘솔 + (선택) 파일 핸들러.

    ``logging.basicConfig`` 를 사용하므로 프로세스 내 첫 호출만 실제 설정이 적용된다.
    기존 스크립트의 ``setup_logging()`` 과 동일한 동작을 보장한다.

    Args:
        name: 로거 이름 (예: ``"p5_email_triage"``)
        log_file: 로그 파일 경로 (``None`` 이면 콘솔만)
        level: 로깅 레벨

    Returns:
        구성된 ``logging.Logger`` 인스턴스
    """
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_path, encoding="utf-8"))

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=handlers,
    )
    return logging.getLogger(name)
