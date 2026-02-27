#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Google API 유틸리티 모듈

서비스 계정 인증, Drive/Sheets/Docs 클라이언트 팩토리,
파일 다운로드/검색 헬퍼 함수 제공.

재사용 패턴: p5_issue_sync.py GoogleSheetsClient (L264-289)
"""

from __future__ import annotations

import io
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

log = logging.getLogger(__name__)

# ─── 경로 설정 ───────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent          # scripts/telegram/
SCRIPTS_DIR = SCRIPT_DIR.parent                        # scripts/
PROJECT_ROOT = SCRIPTS_DIR.parent                      # 14.AI_Agent/
CREDENTIALS_PATH = PROJECT_ROOT / ".secrets" / "google-sheets-credentials.json"
CONFIG_PATH = PROJECT_ROOT / "ResearchVault" / "_config" / "p5-sync-config.yaml"

# Google API Scopes
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents.readonly",
]

# Google Workspace MIME types → export formats
_EXPORT_MAP: Dict[str, Tuple[str, str]] = {
    "application/vnd.google-apps.document": (
        "text/plain", ".txt"
    ),
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsx",
    ),
    "application/vnd.google-apps.presentation": (
        "application/pdf", ".pdf"
    ),
}

# MIME type → 아이콘
_MIME_ICONS: Dict[str, str] = {
    "application/pdf": "📕",
    "application/vnd.google-apps.document": "📝",
    "application/vnd.google-apps.spreadsheet": "📊",
    "application/vnd.google-apps.presentation": "📙",
    "application/vnd.google-apps.folder": "📂",
    "image/": "🖼️",
    "video/": "🎬",
    "application/vnd.openxmlformats-officedocument.spreadsheetml": "📊",
    "application/vnd.openxmlformats-officedocument.wordprocessingml": "📄",
    "application/vnd.openxmlformats-officedocument.presentationml": "📙",
}

# Google URL patterns
_URL_PATTERNS = [
    # Google Docs
    (re.compile(r"docs\.google\.com/document/d/([a-zA-Z0-9_-]+)"), "document"),
    # Google Sheets
    (re.compile(r"docs\.google\.com/spreadsheets/d/([a-zA-Z0-9_-]+)"), "spreadsheet"),
    # Google Slides
    (re.compile(r"docs\.google\.com/presentation/d/([a-zA-Z0-9_-]+)"), "presentation"),
    # Google Drive file
    (re.compile(r"drive\.google\.com/file/d/([a-zA-Z0-9_-]+)"), "file"),
    # Google Drive folder
    (re.compile(r"drive\.google\.com/drive/(?:u/\d+/)?folders/([a-zA-Z0-9_-]+)"), "folder"),
    # open?id= format
    (re.compile(r"drive\.google\.com/open\?id=([a-zA-Z0-9_-]+)"), "file"),
]


# ═══════════════════════════════════════════════════════════════
#  인증 및 클라이언트 팩토리
# ═══════════════════════════════════════════════════════════════

def get_google_credentials():
    """서비스 계정 인증 정보 로딩.

    Returns:
        google.oauth2.service_account.Credentials or None
    """
    try:
        from google.oauth2.service_account import Credentials
    except ImportError:
        log.error("google-auth 패키지가 필요합니다: pip install google-auth")
        return None

    if not CREDENTIALS_PATH.exists():
        log.error(f"인증 파일이 없습니다: {CREDENTIALS_PATH}")
        return None

    try:
        creds = Credentials.from_service_account_file(
            str(CREDENTIALS_PATH), scopes=SCOPES
        )
        return creds
    except Exception as e:
        log.error(f"서비스 계정 인증 실패: {e}")
        return None


def get_drive_service():
    """Google Drive API v3 서비스 생성.

    Returns:
        googleapiclient.discovery.Resource or None
    """
    creds = get_google_credentials()
    if not creds:
        return None

    try:
        from googleapiclient.discovery import build
        return build("drive", "v3", credentials=creds)
    except ImportError:
        log.error("google-api-python-client 필요: pip install google-api-python-client")
        return None
    except Exception as e:
        log.error(f"Drive 서비스 생성 실패: {e}")
        return None


def get_docs_service():
    """Google Docs API v1 서비스 생성.

    Returns:
        googleapiclient.discovery.Resource or None
    """
    creds = get_google_credentials()
    if not creds:
        return None

    try:
        from googleapiclient.discovery import build
        return build("docs", "v1", credentials=creds)
    except ImportError:
        log.error("google-api-python-client 필요: pip install google-api-python-client")
        return None
    except Exception as e:
        log.error(f"Docs 서비스 생성 실패: {e}")
        return None


def get_sheets_client():
    """gspread 클라이언트 생성 (기존 p5_issue_sync.py 패턴).

    Returns:
        gspread.Client or None
    """
    creds = get_google_credentials()
    if not creds:
        return None

    try:
        import gspread
        return gspread.authorize(creds)
    except ImportError:
        log.error("gspread 필요: pip install gspread")
        return None
    except Exception as e:
        log.error(f"gspread 인증 실패: {e}")
        return None


# ═══════════════════════════════════════════════════════════════
#  설정 로딩
# ═══════════════════════════════════════════════════════════════

def _load_config() -> dict:
    """p5-sync-config.yaml 로딩."""
    if not CONFIG_PATH.exists():
        return {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        log.warning(f"설정 파일 로딩 실패: {e}")
        return {}


def get_drive_folder_id() -> Optional[str]:
    """P5 프로젝트 Drive 폴더 ID 로딩.

    우선순위: .env GOOGLE_DRIVE_FOLDER_ID > config google_drive.folder_id
    """
    # 1. .env
    env_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID", "").strip()
    if env_id:
        return env_id

    # 2. dotenv 파일
    try:
        from dotenv import dotenv_values
        env_path = PROJECT_ROOT / ".env"
        if env_path.exists():
            env_vals = dotenv_values(str(env_path))
            env_id = env_vals.get("GOOGLE_DRIVE_FOLDER_ID", "").strip()
            if env_id:
                return env_id
    except ImportError:
        pass

    # 3. config
    cfg = _load_config()
    gdrive_cfg = cfg.get("google_drive", {})
    folder_id = gdrive_cfg.get("folder_id", "").strip()
    return folder_id if folder_id else None


def get_default_spreadsheet_id() -> Optional[str]:
    """기본 스프레드시트 ID (p5-sync-config.yaml)."""
    cfg = _load_config()
    return cfg.get("spreadsheet_id", "").strip() or None


def get_default_sheet_name() -> str:
    """기본 시트 이름 (p5-sync-config.yaml)."""
    cfg = _load_config()
    return cfg.get("sheet_name", "접수 메일").strip()


# ═══════════════════════════════════════════════════════════════
#  Google Drive 함수
# ═══════════════════════════════════════════════════════════════

def drive_list_files(
    folder_id: Optional[str] = None,
    query: Optional[str] = None,
    max_results: int = 20,
    file_type: Optional[str] = None,
) -> List[Dict[str, str]]:
    """Drive 파일 목록/검색.

    Args:
        folder_id: 폴더 ID (None이면 공유된 전체 검색)
        query: 파일명 검색어
        max_results: 최대 결과 수
        file_type: MIME 타입 필터 (예: 'application/pdf')

    Returns:
        [{"id", "name", "mimeType", "modifiedTime", "size", "webViewLink"}]
    """
    service = get_drive_service()
    if not service:
        return []

    # q 파라미터 빌드
    q_parts = ["trashed = false"]
    if folder_id:
        q_parts.append(f"'{folder_id}' in parents")
    if query:
        safe_query = query.replace("\\", "\\\\").replace("'", "\\'")
        q_parts.append(f"name contains '{safe_query}'")
    if file_type:
        q_parts.append(f"mimeType contains '{file_type}'")

    q = " and ".join(q_parts)

    try:
        results = service.files().list(
            q=q,
            pageSize=max_results,
            fields="files(id,name,mimeType,modifiedTime,size,webViewLink)",
            orderBy="modifiedTime desc",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()

        files = results.get("files", [])
        return [
            {
                "id": f.get("id", ""),
                "name": f.get("name", ""),
                "mimeType": f.get("mimeType", ""),
                "modifiedTime": f.get("modifiedTime", ""),
                "size": f.get("size", "0"),
                "webViewLink": f.get("webViewLink", ""),
            }
            for f in files
        ]
    except Exception as e:
        log.error(f"Drive 파일 목록 조회 실패: {e}")
        return []


def drive_get_file_metadata(file_id: str) -> Optional[Dict]:
    """단일 파일 메타데이터 조회."""
    service = get_drive_service()
    if not service:
        return None

    try:
        return service.files().get(
            fileId=file_id,
            fields="id,name,mimeType,modifiedTime,size,webViewLink,parents",
            supportsAllDrives=True,
        ).execute()
    except Exception as e:
        log.error(f"파일 메타데이터 조회 실패 ({file_id}): {e}")
        return None


def drive_download_file(
    file_id: str,
    output_dir: str,
    filename: Optional[str] = None,
) -> Optional[str]:
    """Drive 파일 다운로드.

    Google Workspace 파일은 export, 일반 파일은 직접 다운로드.

    Returns:
        다운로드된 파일 경로 (절대경로) 또는 None
    """
    from googleapiclient.http import MediaIoBaseDownload

    service = get_drive_service()
    if not service:
        return None

    try:
        # 메타데이터로 파일 타입 확인
        meta = service.files().get(
            fileId=file_id,
            fields="name,mimeType,size",
            supportsAllDrives=True,
        ).execute()

        # Check download size limit
        file_size = int(meta.get("size", 0) or 0)
        cfg = _load_config()
        max_mb = cfg.get("google_drive", {}).get("max_download_size_mb", 100)
        if file_size > 0 and file_size > max_mb * 1024 * 1024:
            log.warning(
                "File too large: %s (%d bytes, limit %dMB)",
                meta.get("name"), file_size, max_mb,
            )
            return None

        mime = meta.get("mimeType", "")
        name = filename or meta.get("name", "download")

        # Google Workspace → export
        if mime in _EXPORT_MAP:
            export_mime, ext = _EXPORT_MAP[mime]
            if not name.endswith(ext):
                name = Path(name).stem + ext

            request = service.files().export_media(
                fileId=file_id, mimeType=export_mime
            )
        else:
            # 일반 바이너리 파일
            request = service.files().get_media(
                fileId=file_id, supportsAllDrives=True
            )

        # 다운로드
        os.makedirs(output_dir, exist_ok=True)
        # 파일명 안전 처리 (Windows 금지 문자 제거)
        safe_name = re.sub(r'[<>:"/\\|?*]', '_', name)
        output_path = os.path.join(output_dir, safe_name)

        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)

        done = False
        while not done:
            _, done = downloader.next_chunk()

        with open(output_path, "wb") as f:
            f.write(buffer.getvalue())

        log.info(f"다운로드 완료: {output_path} ({len(buffer.getvalue())} bytes)")
        return output_path

    except Exception as e:
        log.error(f"파일 다운로드 실패 ({file_id}): {e}")
        return None


# ═══════════════════════════════════════════════════════════════
#  Google Docs 함수
# ═══════════════════════════════════════════════════════════════

def docs_get_text(doc_id: str) -> Optional[str]:
    """Google Docs 문서 텍스트 추출.

    Args:
        doc_id: 문서 ID

    Returns:
        순수 텍스트 또는 None
    """
    service = get_docs_service()
    if not service:
        return None

    try:
        doc = service.documents().get(documentId=doc_id).execute()
        body = doc.get("body", {})
        content = body.get("content", [])

        text_parts = []
        for element in content:
            paragraph = element.get("paragraph")
            if not paragraph:
                continue
            for pe in paragraph.get("elements", []):
                text_run = pe.get("textRun")
                if text_run:
                    text_parts.append(text_run.get("content", ""))

        return "".join(text_parts)
    except Exception as e:
        log.error(f"Docs 텍스트 추출 실패 ({doc_id}): {e}")
        return None


# ═══════════════════════════════════════════════════════════════
#  Google Sheets 함수
# ═══════════════════════════════════════════════════════════════

def sheets_read_range(
    spreadsheet_id: str,
    sheet_name: str,
    cell_range: Optional[str] = None,
) -> Tuple[List[str], List[List[str]]]:
    """Google Sheets 데이터 읽기.

    Args:
        spreadsheet_id: 스프레드시트 ID
        sheet_name: 시트(탭) 이름
        cell_range: A1 표기법 범위 (None이면 전체)

    Returns:
        (headers, rows) — headers가 비어있으면 오류
    """
    client = get_sheets_client()
    if not client:
        return [], []

    try:
        spreadsheet = client.open_by_key(spreadsheet_id)
        worksheet = spreadsheet.worksheet(sheet_name)

        if cell_range:
            data = worksheet.get(cell_range)
        else:
            data = worksheet.get_all_values()

        if not data:
            return [], []

        headers = data[0] if data else []
        rows = data[1:] if len(data) > 1 else []
        return headers, rows

    except Exception as e:
        log.error(f"Sheets 읽기 실패: {e}")
        return [], []


def sheets_write_cells(
    spreadsheet_id: str,
    sheet_name: str,
    updates: List[Dict[str, str]],
) -> int:
    """Google Sheets 셀 쓰기.

    Args:
        spreadsheet_id: 스프레드시트 ID
        sheet_name: 시트 이름
        updates: [{"cell": "B5", "value": "진행중"}, ...]

    Returns:
        업데이트된 셀 수
    """
    client = get_sheets_client()
    if not client:
        return 0

    try:
        spreadsheet = client.open_by_key(spreadsheet_id)
        worksheet = spreadsheet.worksheet(sheet_name)

        count = 0
        for upd in updates:
            cell = upd.get("cell", "").strip()
            value = upd.get("value", "")
            if not cell:
                continue
            worksheet.update_acell(cell, value)
            count += 1

        return count
    except Exception as e:
        log.error(f"Sheets 쓰기 실패: {e}")
        return 0


def sheets_list_worksheets(spreadsheet_id: str) -> List[str]:
    """스프레드시트 내 시트(탭) 목록."""
    client = get_sheets_client()
    if not client:
        return []

    try:
        spreadsheet = client.open_by_key(spreadsheet_id)
        return [ws.title for ws in spreadsheet.worksheets()]
    except Exception as e:
        log.error(f"시트 목록 조회 실패: {e}")
        return []


# ═══════════════════════════════════════════════════════════════
#  URL 파싱
# ═══════════════════════════════════════════════════════════════

def parse_drive_url(url: str) -> Optional[Tuple[str, str]]:
    """Google Drive/Docs/Sheets URL에서 ID와 타입 추출.

    Returns:
        (file_id, type) — type: file|folder|spreadsheet|document|presentation
        None이면 Google URL이 아님
    """
    for pattern, url_type in _URL_PATTERNS:
        match = pattern.search(url)
        if match:
            return match.group(1), url_type
    return None


def detect_google_url(text: str) -> Optional[Tuple[str, str]]:
    """텍스트에서 Google URL을 찾아서 파싱.

    Returns:
        (file_id, type) 또는 None
    """
    url_pattern = re.compile(r'https?://[^\s<>"]+google[^\s<>"]+')
    for match in url_pattern.finditer(text):
        result = parse_drive_url(match.group())
        if result:
            return result
    return None


# ═══════════════════════════════════════════════════════════════
#  유틸리티
# ═══════════════════════════════════════════════════════════════

def get_mime_icon(mime_type: str) -> str:
    """MIME 타입에 맞는 아이콘 반환."""
    for prefix, icon in _MIME_ICONS.items():
        if mime_type.startswith(prefix):
            return icon
    return "📄"


def format_file_size(size_bytes: int) -> str:
    """파일 크기 사람이 읽을 수 있는 형식."""
    if size_bytes < 1024:
        return f"{size_bytes}B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f}KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f}MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f}GB"


def format_date_short(iso_date: str) -> str:
    """ISO 날짜 → 짧은 형식 (2026-02-13)."""
    if not iso_date:
        return ""
    return iso_date[:10]
