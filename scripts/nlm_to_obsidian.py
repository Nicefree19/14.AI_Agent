"""
NotebookLM → Obsidian 역방향 동기화
NotebookLM에서 인사이트/요약을 추출하여 Obsidian 마크다운으로 변환 후 저장
"""

import sys
import re
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

import yaml

try:
    from notebooklm_mcp.auth import load_cached_tokens
    from notebooklm_mcp.api_client import NotebookLMClient
except ImportError as e:
    print(f"모듈 임포트 오류: {e}")
    print("notebooklm-mcp-server가 설치되어 있는지 확인하세요.")
    sys.exit(1)

# ─── sys.path 보정 (bare import 호환) ──────────────────────
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

# ─── 설정 ─────────────────────────────────────────────────
from p5_config import VAULT_PATH, SCRIPT_DIR
from p5_utils import setup_logger

PROJECTS_DIR = VAULT_PATH / "03-Projects"
NOTES_DIR = VAULT_PATH / "02-Notes"
SOURCES_DIR = VAULT_PATH / "01-Sources"

log = setup_logger("nlm_to_obsidian", SCRIPT_DIR / "nlm_sync.log")


# ─── Alert ──────────────────────────────────────────────────
def send_telegram_alert(message: str):
    """오류 발생 시 텔레그램 알림 전송"""
    try:
        script_dir = Path(__file__).parent
        if str(script_dir) not in sys.path:
            sys.path.append(str(script_dir))

        from telegram.telegram_sender import send_message_sync
        from dotenv import load_dotenv
        import os

        env_path = script_dir.parent / ".env"
        load_dotenv(env_path)

        allowed = os.getenv("TELEGRAM_ALLOWED_USERS", "")
        if allowed:
            chat_id = allowed.split(",")[0].strip()
            if chat_id:
                send_message_sync(
                    chat_id, f"🚨 **NotebookLM 동기화 오류**\n\n{message}"
                )
    except Exception as e:
        log.error(f"텔레그램 알림 전송 실패: {e}")


# ─── NotebookLM 클라이언트 초기화 ─────────────────────────
def create_client() -> Optional[NotebookLMClient]:
    """인증 토큰으로 NotebookLM 클라이언트 생성"""
    try:
        tokens = load_cached_tokens()
    except Exception as e:
        msg = f"인증 토큰 로드 실패: {e}\n👉 재인증이 필요합니다. 'scripts/auth_notebooklm.bat'를 실행하세요."
        log.error(msg)
        send_telegram_alert(msg)
        return None

    if not tokens:
        msg = "인증 토큰 없음.\n👉 재인증이 필요합니다. 'scripts/auth_notebooklm.bat'를 실행하세요."
        log.error(msg)
        send_telegram_alert(msg)
        return None

    # 토큰 유효성 간단 체크 (실제 만료 여부는 API 호출 시 확인됨)
    # 하지만 load_cached_tokens()가 이미 만료 체크를 내부적으로 수행할 수 있음

    NotebookLMClient._PAGE_FETCH_HEADERS["User-Agent"] = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"
    )
    NotebookLMClient._PAGE_FETCH_HEADERS["sec-ch-ua-platform"] = '"Windows"'

    try:
        client = NotebookLMClient(
            cookies=tokens.cookies,
            csrf_token=tokens.csrf_token,
            session_id=tokens.session_id,
        )

        import httpx

        cookie_str = "; ".join(f"{k}={v}" for k, v in tokens.cookies.items())
        client._client = httpx.Client(
            headers={
                "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                "Origin": "https://notebooklm.google.com",
                "Referer": "https://notebooklm.google.com/",
                "Cookie": cookie_str,
                "X-Same-Domain": "1",
                "User-Agent": NotebookLMClient._PAGE_FETCH_HEADERS["User-Agent"],
            },
            timeout=60.0,
        )
        return client
    except Exception as e:
        msg = f"클라이언트 초기화 실패: {e}\n👉 재인증이 필요합니다. 'scripts/auth_notebooklm.bat'를 실행하세요."
        log.error(msg)
        send_telegram_alert(msg)
        return None


# ─── WikiLink 생성 ────────────────────────────────────────
def find_related_notes(topic: str) -> list[str]:
    """Vault에서 주제와 관련된 기존 노트를 검색하여 WikiLink 목록 반환"""
    related = []
    keywords = [
        kw.strip().lower() for kw in re.split(r"[\s,]+", topic) if len(kw.strip()) > 1
    ]

    for md_file in VAULT_PATH.rglob("*.md"):
        # 설정/템플릿 폴더 제외
        rel = md_file.relative_to(VAULT_PATH)
        skip_dirs = {
            "_config",
            "Templates",
            "Rules",
            "Workflows",
            "Skills",
            ".obsidian",
        }
        if any(part in skip_dirs for part in rel.parts):
            continue

        try:
            content = md_file.read_text(encoding="utf-8").lower()
            stem = md_file.stem.lower()
            # 키워드 매칭
            matches = sum(1 for kw in keywords if kw in content or kw in stem)
            if matches >= 1:
                related.append(md_file.stem)
        except Exception:
            continue

    return related[:10]  # 최대 10개


def slugify(text: str) -> str:
    """파일명 안전한 슬러그 생성"""
    text = re.sub(r"[^\w\s가-힣-]", "", text)
    text = re.sub(r"\s+", "-", text.strip())
    return text[:80]


# ─── Auto-Linker Setup ──────────────────────────────────────
try:
    from p5_autolinker import AutoLinker

    _linker = None
except ImportError:
    import logging

    logging.getLogger().warning("p5_autolinker 모듈을 찾을 수 없습니다.")
    _linker = None


def _auto_link(text: str) -> str:
    global _linker
    if not text:
        return text

    if _linker is None:
        try:
            _linker = AutoLinker()
            _linker.build_index()
        except NameError:
            return text
        except Exception:
            return text

    return _linker.link_text(text)


# ─── 마크다운 변환 ────────────────────────────────────────
def build_obsidian_note(
    title: str,
    notebook_title: str,
    notebook_id: str,
    summary_text: str,
    topics: list[str],
    related_notes: list[str],
) -> str:
    """NotebookLM 인사이트를 Obsidian 마크다운으로 변환"""
    today = datetime.now().strftime("%Y-%m-%d")

    # Auto-Linking
    summary_text = _auto_link(summary_text)

    # YAML Frontmatter
    frontmatter = {
        "title": title,
        "tags": ["type/research", "status/draft", "source/notebooklm"],
        "date": today,
        "source": f"NotebookLM/{notebook_title}",
        "notebook_id": notebook_id,
        "related": [f"[[{note}]]" for note in related_notes[:5]],
    }

    lines = ["---"]
    lines.append(
        yaml.dump(frontmatter, allow_unicode=True, default_flow_style=False).rstrip()
    )
    lines.append("---")
    lines.append("")
    lines.append(f"# {title}")
    lines.append("")

    # 요약 섹션
    lines.append("## 요약")
    if summary_text:
        lines.append(summary_text)
    else:
        lines.append("_요약 정보 없음_")
    lines.append("")

    # 핵심 토픽
    if topics:
        lines.append("## 핵심 토픽")
        for i, topic in enumerate(topics, 1):
            if isinstance(topic, str):
                lines.append(f"{i}. {topic}")
            elif isinstance(topic, list) and topic:
                lines.append(f"{i}. {topic[0]}")
        lines.append("")

    # 관련 노트 (WikiLinks)
    lines.append("## 관련 노트")
    if related_notes:
        for note in related_notes:
            lines.append(f"- [[{note}]]")
    else:
        lines.append("- _관련 노트 없음_")
    lines.append("")

    # 출처
    lines.append("## 출처")
    lines.append(f"- NotebookLM: {notebook_title}")
    lines.append(f"- 동기화 일시: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"<!-- source: NotebookLM/{notebook_title} -->")
    lines.append("")

    return "\n".join(lines)


# ─── Context Integration ────────────────────────────────────
def update_sheet_context(notebook_title: str, text: str):
    """텍스트에서 이슈 ID를 찾아 Google Sheets '관련도면' 컬럼에 링크 추가"""
    # 1. 이슈 ID 추출 (SEN-000 형식)
    issue_ids = set(re.findall(r"SEN-\d{3,}", text, re.IGNORECASE))

    # 제목에도 이슈 ID가 있을 수 있음
    issue_ids.update(re.findall(r"SEN-\d{3,}", notebook_title, re.IGNORECASE))

    if not issue_ids:
        return

    log.info(f"🔍 관련 이슈 발견: {', '.join(issue_ids)}")

    try:
        # p5_issue_sync 모듈 로드
        script_dir = Path(__file__).parent
        if str(script_dir) not in sys.path:
            sys.path.append(str(script_dir))

        from p5_issue_sync import GoogleSheetsClient, CONFIG_PATH, CREDENTIALS_PATH

        # 설정 로드 (Spreadsheet ID)
        if not CONFIG_PATH.exists():
            log.error(f"설정 파일 없음: {CONFIG_PATH}")
            return

        config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
        spreadsheet_id = config.get("spreadsheet_id", "")
        sheet_name = config.get("sheet_name", "접수 메일")

        if not spreadsheet_id:
            log.error("Spreadsheet ID가 설정되지 않았습니다.")
            return

        # Sheets 연결
        client = GoogleSheetsClient(CREDENTIALS_PATH)
        if not client.connect(spreadsheet_id, sheet_name):
            return

        # 링크 텍스트 (예: "NotebookLM: 2024-02-13 회의록")
        link_text = f"NotebookLM: {notebook_title}"

        # 각 이슈에 추가
        for issue_id in issue_ids:
            client.append_to_issue(issue_id, "관련도면", link_text)

    except Exception as e:
        log.error(f"Sheets 컨텍스트 업데이트 실패: {e}")


# ─── 메인 동기화 로직 ─────────────────────────────────────
def sync_notebook(
    client: NotebookLMClient, notebook, save_dir: Path = PROJECTS_DIR
) -> Optional[Path]:
    """단일 노트북에서 인사이트 추출 후 Obsidian에 저장"""
    nb_id = notebook.id
    nb_title = notebook.title or "Untitled"

    log.info(f"[추출] '{nb_title}' (ID: {nb_id})")

    summary_text = ""
    topics = []

    try:
        result = client._call_rpc(
            client.RPC_GET_SUMMARY,
            [nb_id],
            path=f"/notebook/{nb_id}",
            timeout=30.0,
        )

        if result and isinstance(result, list):
            if len(result) > 0 and result[0]:
                raw = result[0]
                if isinstance(raw, str):
                    summary_text = raw
                elif isinstance(raw, list) and raw:
                    summary_text = str(raw[0])

            if len(result) > 1 and result[1]:
                raw_topics = result[1]
                if isinstance(raw_topics, list):
                    topics = raw_topics[:10]

    except Exception as e:
        log.warning(f"[경고] '{nb_title}' 요약 추출 실패: {e}")

    # 관련 노트 검색
    related = find_related_notes(nb_title)

    # 마크다운 생성
    note_title = f"{nb_title} - NotebookLM 인사이트"
    content = build_obsidian_note(
        title=note_title,
        notebook_title=nb_title,
        notebook_id=nb_id,
        summary_text=summary_text,
        topics=topics,
        related_notes=related,
    )

    # 파일 저장
    today = datetime.now().strftime("%Y%m%d")
    slug = slugify(nb_title)
    filename = f"{today}-{slug}-insights.md"
    filepath = save_dir / filename

    save_dir.mkdir(parents=True, exist_ok=True)
    filepath.write_text(content, encoding="utf-8")
    log.info(f"[저장] {filepath.relative_to(VAULT_PATH)}")

    # Google Sheets 컨텍스트 업데이트 (역링크)
    full_text = f"{summary_text}\n{' '.join(topics)}"
    update_sheet_context(nb_title, full_text)

    return filepath


def sync_all(limit: int = 10) -> list[Path]:
    """모든 활성 노트북에서 인사이트 추출 후 저장"""
    client = create_client()
    if not client:
        return []

    log.info("=== NotebookLM -> Obsidian 역방향 동기화 시작 ===")

    try:
        notebooks = client.list_notebooks()
    except Exception as e:
        msg = f"노트북 목록 조회 실패: {e}"
        log.error(msg)
        send_telegram_alert(msg)
        return []

    active = [nb for nb in notebooks if nb.source_count > 0 and nb.title]
    active.sort(key=lambda x: x.source_count, reverse=True)
    target = active[:limit]

    log.info(f"대상 노트북: {len(target)}개 (전체 {len(active)}개 중)")

    saved_files = []
    for nb in target:
        try:
            filepath = sync_notebook(client, nb)
            if filepath:
                saved_files.append(filepath)
        except Exception as e:
            log.error(f"[오류] '{nb.title}' 동기화 실패: {e}")

    log.info(f"=== 동기화 완료: {len(saved_files)}개 파일 저장 ===")
    return saved_files


def sync_single(notebook_name: str) -> Optional[Path]:
    """이름으로 특정 노트북 동기화"""
    client = create_client()
    if not client:
        return None

    try:
        notebooks = client.list_notebooks()
    except Exception as e:
        msg = f"노트북 목록 조회 실패: {e}"
        log.error(msg)
        send_telegram_alert(msg)
        return None

    # 이름 매칭
    target = None
    name_lower = notebook_name.lower()
    for nb in notebooks:
        if nb.title and name_lower in nb.title.lower():
            target = nb
            break

    if not target:
        log.error(f"'{notebook_name}' 이름의 노트북을 찾을 수 없습니다.")
        return None

    return sync_notebook(client, target)


# ─── CLI ──────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="NotebookLM -> Obsidian 역방향 동기화")
    parser.add_argument("--all", action="store_true", help="모든 활성 노트북 동기화")
    parser.add_argument("--notebook", type=str, help="특정 노트북 이름으로 동기화")
    parser.add_argument(
        "--limit", type=int, default=10, help="동기화할 최대 노트북 수 (기본: 10)"
    )
    args = parser.parse_args()

    if args.notebook:
        result = sync_single(args.notebook)
        if result:
            print(f"\n저장 완료: {result}")
    else:
        results = sync_all(limit=args.limit)
        if results:
            print(f"\n총 {len(results)}개 파일 저장 완료:")
            for f in results:
                print(f"  - {f.relative_to(VAULT_PATH)}")
