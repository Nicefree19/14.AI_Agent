"""
p5_config — P5 프로젝트 공통 경로 상수.

모든 경로는 이 파일(__file__)의 위치를 기준으로 동적 계산된다.
절대 하드코딩 경로(D:\\...)를 사용하지 않는다.

Usage::

    from p5_config import VAULT_PATH, ISSUES_DIR, resolve_path
"""

from __future__ import annotations

from pathlib import Path

# ── 루트 계산 ────────────────────────────────────────────
SCRIPT_DIR: Path = Path(__file__).resolve().parent          # scripts/
PROJECT_ROOT: Path = SCRIPT_DIR.parent                      # 14.AI_Agent/

# ── Obsidian Vault ───────────────────────────────────────
VAULT_PATH: Path = PROJECT_ROOT / "ResearchVault"

# ── 핵심 디렉토리 ───────────────────────────────────────
LOG_DIR: Path = PROJECT_ROOT / "logs"
TELEGRAM_DATA_DIR: Path = PROJECT_ROOT / "telegram_data"
CONFIG_DIR: Path = VAULT_PATH / "_config"
SECRETS_DIR: Path = PROJECT_ROOT / ".secrets"

# ── Vault 하위 디렉토리 ─────────────────────────────────
ISSUES_DIR: Path = VAULT_PATH / "P5-Project" / "01-Issues"
OVERVIEW_DIR: Path = VAULT_PATH / "P5-Project" / "00-Overview"
INBOX_DIR: Path = VAULT_PATH / "00-Inbox" / "Messages" / "Emails"

# ── 설정 파일 ────────────────────────────────────────────
TRIAGE_RULES_PATH: Path = CONFIG_DIR / "p5-triage-rules.yaml"
SYNC_CONFIG_PATH: Path = CONFIG_DIR / "p5-sync-config.yaml"
INGEST_POLICY_PATH: Path = CONFIG_DIR / "ingest-policy.yaml"

# ── 자격 증명 ────────────────────────────────────────────
CREDENTIALS_PATH: Path = SECRETS_DIR / "google-sheets-credentials.json"


def resolve_path(p: str | Path) -> Path:
    """경로 해석: 상대경로면 PROJECT_ROOT 기준, 절대경로면 그대로.

    Args:
        p: 문자열 또는 Path 객체

    Returns:
        절대경로 Path
    """
    p = Path(p)
    if p.is_absolute():
        return p
    return PROJECT_ROOT / p
