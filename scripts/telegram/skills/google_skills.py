#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Google 연동 스킬 모듈

- gdrive_browse: Google Drive 파일 목록/검색
- gdrive_download: Google Drive 파일 다운로드
- email_check: 이메일 확인 (Outlook COM / IMAP fallback)
- gsheet_edit: Google Sheets 읽기/쓰기
- gdoc_read: Google Docs 내용 읽기
"""

from __future__ import annotations

import os
import re
import sys
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

# scripts/ 디렉토리 import path
_SCRIPTS_DIR = str(Path(__file__).resolve().parent.parent.parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

# ─── 트리거 키워드 제거용 패턴 ───────────────────────────────
_BROWSE_KEYWORDS = [
    "드라이브검색", "드라이브목록", "구글드라이브", "공유폴더",
    "drive검색", "drive목록", "drive", "파일목록", "파일 목록",
    "확인", "조회", "검색", "목록",
]
_DOWNLOAD_KEYWORDS = [
    "드라이브다운", "파일다운로드", "drive다운", "다운로드", "다운",
    "받기", "가져오기", "가져와",
]
_EMAIL_KEYWORDS = [
    "메일확인", "메일조회", "받은메일", "최근메일", "gmail",
    "확인", "조회", "오늘", "최근",
]
_SHEET_KEYWORDS = [
    "시트수정", "시트조회", "구글시트", "스프레드시트",
    "sheets", "수정", "변경", "조회", "확인", "기록",
]
_DOC_KEYWORDS = [
    "구글문서", "문서읽기", "gdoc", "docs읽기",
    "읽기", "읽어", "확인", "내용",
]


def _strip_keywords(text: str, keywords: List[str]) -> str:
    """텍스트에서 트리거 키워드를 제거하여 실제 검색어 추출."""
    result = text.lower().strip()
    for kw in sorted(keywords, key=len, reverse=True):
        result = result.replace(kw, "")
    # URL은 유지, 나머지 정리
    result = re.sub(r'\s+', ' ', result).strip()
    return result


# ═══════════════════════════════════════════════════════════════
#  1. Google Drive 파일 검색
# ═══════════════════════════════════════════════════════════════

def run_gdrive_browse(context: dict) -> dict:
    """Google Drive 공유 폴더 파일 목록 및 검색."""
    send_progress = context.get("send_progress", lambda x: None)
    send_progress("📂 Google Drive 파일 목록 조회 중...")

    try:
        from scripts.telegram.google_utils import (
            drive_list_files, get_drive_folder_id,
            detect_google_url, parse_drive_url,
            get_mime_icon, format_file_size, format_date_short,
        )

        combined = context.get("combined", {})
        instruction = combined.get("combined_instruction", "")

        # 1. URL이 있으면 해당 폴더 조회
        url_result = detect_google_url(instruction)
        folder_id = None
        if url_result:
            fid, ftype = url_result
            if ftype == "folder":
                folder_id = fid
            else:
                # 폴더가 아닌 URL → 해당 파일 메타데이터
                from scripts.telegram.google_utils import drive_get_file_metadata
                meta = drive_get_file_metadata(fid)
                if meta:
                    icon = get_mime_icon(meta.get("mimeType", ""))
                    size = format_file_size(int(meta.get("size", "0") or "0"))
                    date = format_date_short(meta.get("modifiedTime", ""))
                    return {
                        "result_text": (
                            f"📂 Google Drive 파일 정보\n"
                            f"━━━━━━━━━━━━━━━━━━━━\n"
                            f"{icon} {meta['name']}\n"
                            f"  크기: {size} | 수정: {date}\n"
                            f"  타입: {meta.get('mimeType', '')}\n"
                            f"  링크: {meta.get('webViewLink', '')}"
                        ),
                        "files": [],
                    }

        # 2. 검색 키워드 추출
        search_query = _strip_keywords(instruction, _BROWSE_KEYWORDS)
        # URL 제거
        search_query = re.sub(r'https?://\S+', '', search_query).strip()

        # 3. 폴더 ID 결정
        if not folder_id:
            folder_id = get_drive_folder_id()

        if not folder_id and not search_query:
            return {
                "result_text": (
                    "⚠️ Google Drive 폴더 ID가 설정되지 않았습니다.\n\n"
                    "설정 방법:\n"
                    "1. P5 프로젝트 Drive 폴더를 서비스 계정에 공유:\n"
                    "   p5-sync-agent@model-wave-468712-e5.iam.gserviceaccount.com\n"
                    "2. p5-sync-config.yaml에 폴더 ID 입력:\n"
                    "   google_drive:\n"
                    "     folder_id: \"폴더URL에서_추출한_ID\""
                ),
                "files": [],
            }

        # 4. 파일 목록 조회
        files = drive_list_files(
            folder_id=folder_id,
            query=search_query if search_query else None,
            max_results=20,
        )

        if not files:
            msg = "파일이 없습니다."
            if search_query:
                msg = f"'{search_query}' 검색 결과가 없습니다."
            return {"result_text": f"📂 Google Drive\n{msg}", "files": []}

        # 5. 결과 포맷
        lines = ["📂 Google Drive 파일 목록", "━━━━━━━━━━━━━━━━━━━━"]
        if search_query:
            lines.append(f"🔍 검색: {search_query}")
            lines.append("")

        for f in files:
            icon = get_mime_icon(f["mimeType"])
            size = format_file_size(int(f.get("size", "0") or "0"))
            date = format_date_short(f["modifiedTime"])
            lines.append(f"{icon} {f['name']}  ({size}, {date})")

        lines.append(f"\n총 {len(files)}개 파일")

        return {"result_text": "\n".join(lines), "files": []}

    except ImportError as e:
        return {
            "result_text": f"⚠️ Google API 패키지가 설치되지 않았습니다: {e}",
            "files": [],
        }
    except Exception as e:
        return {
            "result_text": f"❌ Drive 조회 오류: {e}\n{traceback.format_exc()[-500:]}",
            "files": [],
        }


# ═══════════════════════════════════════════════════════════════
#  2. Google Drive 파일 다운로드
# ═══════════════════════════════════════════════════════════════

def run_gdrive_download(context: dict) -> dict:
    """Google Drive 파일 다운로드 후 텔레그램 전송."""
    send_progress = context.get("send_progress", lambda x: None)
    send_progress("📥 Google Drive 파일 다운로드 중...")

    try:
        from scripts.telegram.google_utils import (
            drive_download_file, drive_list_files, detect_google_url,
            get_drive_folder_id, format_file_size,
        )

        combined = context.get("combined", {})
        instruction = combined.get("combined_instruction", "")
        task_dir = context.get("task_dir", "")

        # 1. URL에서 file_id 추출
        url_result = detect_google_url(instruction)
        file_id = None
        if url_result:
            fid, ftype = url_result
            if ftype == "folder":
                return {
                    "result_text": (
                        "📂 폴더는 다운로드할 수 없습니다.\n"
                        "'드라이브검색' 또는 '구글드라이브' 명령으로 폴더 내용을 확인하세요."
                    ),
                    "files": [],
                }
            file_id = fid

        # 2. URL 없으면 키워드로 검색
        if not file_id:
            search_query = _strip_keywords(instruction, _DOWNLOAD_KEYWORDS)
            search_query = re.sub(r'https?://\S+', '', search_query).strip()

            if not search_query:
                return {
                    "result_text": (
                        "📥 다운로드할 파일을 지정해주세요.\n\n"
                        "사용법:\n"
                        "• Google Drive URL 전송\n"
                        "• '드라이브다운 보고서' (파일명 키워드)"
                    ),
                    "files": [],
                }

            folder_id = get_drive_folder_id()
            results = drive_list_files(
                folder_id=folder_id,
                query=search_query,
                max_results=1,
            )

            if not results:
                return {
                    "result_text": f"❌ '{search_query}' 파일을 찾을 수 없습니다.",
                    "files": [],
                }
            file_id = results[0]["id"]
            send_progress(f"📥 '{results[0]['name']}' 다운로드 중...")

        # 3. 다운로드
        output_dir = task_dir or os.path.join(
            str(Path(__file__).resolve().parent.parent.parent),
            "telegram_data", "tasks", "temp"
        )
        downloaded = drive_download_file(file_id, output_dir)

        if not downloaded:
            return {
                "result_text": "❌ 파일 다운로드에 실패했습니다.",
                "files": [],
            }

        file_size = os.path.getsize(downloaded)
        fname = os.path.basename(downloaded)

        return {
            "result_text": (
                f"📥 다운로드 완료\n"
                f"파일: {fname}\n"
                f"크기: {format_file_size(file_size)}"
            ),
            "files": [downloaded],
        }

    except Exception as e:
        return {
            "result_text": f"❌ 다운로드 오류: {e}\n{traceback.format_exc()[-500:]}",
            "files": [],
        }


# ═══════════════════════════════════════════════════════════════
#  3. 이메일 확인
# ═══════════════════════════════════════════════════════════════

def run_email_check(context: dict) -> dict:
    """이메일 확인 — Outlook COM (1순위) / IMAP (2순위).

    기존 adapters/outlook_adapter.py, adapters/imap_adapter.py 재사용.
    """
    send_progress = context.get("send_progress", lambda x: None)
    send_progress("📧 이메일 확인 중...")

    combined = context.get("combined", {})
    instruction = combined.get("combined_instruction", "")
    text_lower = instruction.lower()

    # 파라미터 추출
    limit = 10
    unread_only = False
    search_keyword = None

    if "오늘" in text_lower:
        limit = 30  # 오늘 것 필터링을 위해 넉넉히
    if "안읽은" in text_lower or "unread" in text_lower:
        unread_only = True

    # 검색 키워드 추출
    search_keyword = _strip_keywords(instruction, _EMAIL_KEYWORDS)
    search_keyword = re.sub(r'https?://\S+', '', search_keyword).strip()

    # 어댑터 시도 순서: Outlook COM → IMAP
    messages = []
    adapter_name = ""

    # 1. Outlook COM 시도
    try:
        from adapters.outlook_adapter import OutlookAdapter
        adapter = OutlookAdapter()
        if adapter.initialize():
            adapter_name = "Outlook"
            raw_msgs = adapter.fetch(limit=limit, unread_only=unread_only)
            messages = raw_msgs
    except Exception as e:
        log.info(f"Outlook 어댑터 실패, IMAP 시도: {e}")

    # 2. IMAP fallback
    if not messages and not adapter_name:
        try:
            from adapters.imap_adapter import IMAPAdapter
            adapter = IMAPAdapter()
            if adapter.initialize():
                adapter_name = "IMAP"
                raw_msgs = adapter.fetch(limit=limit, unread_only=unread_only)
                messages = raw_msgs
        except Exception as e:
            log.info(f"IMAP 어댑터도 실패: {e}")

    if not messages and not adapter_name:
        return {
            "result_text": (
                "⚠️ 이메일 접근 불가\n\n"
                "Outlook이 실행 중이지 않거나, IMAP 설정이 없습니다.\n"
                "• Outlook 데스크톱 앱 실행 후 재시도\n"
                "• 또는 email_config.json에 IMAP 설정 추가"
            ),
            "files": [],
        }

    # 필터링
    today = datetime.now().date()

    filtered = []
    for msg in messages:
        # "오늘" 필터
        if "오늘" in text_lower:
            msg_date = getattr(msg, 'timestamp', None)
            if msg_date and hasattr(msg_date, 'date'):
                if msg_date.date() != today:
                    continue

        # 키워드 필터
        if search_keyword:
            subject = getattr(msg, 'subject', '') or ''
            body = getattr(msg, 'body', '') or ''
            sender = getattr(msg, 'sender', '') or ''
            search_text = f"{subject} {body} {sender}".lower()
            if search_keyword.lower() not in search_text:
                continue

        filtered.append(msg)

    if not filtered:
        msg_text = "검색 조건에 맞는 이메일이 없습니다."
        if search_keyword:
            msg_text = f"'{search_keyword}' 관련 이메일이 없습니다."
        return {
            "result_text": f"📧 이메일 확인 ({adapter_name})\n{msg_text}",
            "files": [],
        }

    # 포맷 (최대 10건)
    show_msgs = filtered[:10]
    lines = [
        f"📧 이메일 확인 ({adapter_name}) — {len(filtered)}건",
        "━━━━━━━━━━━━━━━━━━━━",
    ]

    for i, msg in enumerate(show_msgs, 1):
        sender = getattr(msg, 'sender', '알 수 없음') or '알 수 없음'
        subject = getattr(msg, 'subject', '(제목 없음)') or '(제목 없음)'
        timestamp = getattr(msg, 'timestamp', None)
        body = getattr(msg, 'body', '') or ''

        time_str = ""
        if timestamp:
            if hasattr(timestamp, 'strftime'):
                time_str = timestamp.strftime("%m/%d %H:%M")

        # 본문 미리보기 (100자)
        preview = body.replace('\n', ' ').strip()[:100]
        if len(body.strip()) > 100:
            preview += "..."

        lines.append(f"\n{i}. {subject}")
        lines.append(f"   📤 {sender}  ⏰ {time_str}")
        if preview:
            lines.append(f"   {preview}")

    if len(filtered) > 10:
        lines.append(f"\n... 외 {len(filtered) - 10}건")

    # SEN 참조 감지
    try:
        from scripts.telegram.skill_utils import detect_sen_refs
        all_text = " ".join(
            f"{getattr(m, 'subject', '')} {getattr(m, 'body', '')}"
            for m in show_msgs
        )
        sen_refs = detect_sen_refs(all_text)
        if sen_refs:
            lines.append(f"\n🔗 감지된 이슈 참조: {', '.join(sorted(sen_refs)[:5])}")
    except Exception:
        pass

    return {"result_text": "\n".join(lines), "files": []}


# ═══════════════════════════════════════════════════════════════
#  4. Google Sheets 편집
# ═══════════════════════════════════════════════════════════════

def run_gsheet_edit(context: dict) -> dict:
    """Google Sheets 데이터 조회 및 셀 수정."""
    send_progress = context.get("send_progress", lambda x: None)
    send_progress("📊 Google Sheets 처리 중...")

    try:
        from scripts.telegram.google_utils import (
            detect_google_url, get_default_spreadsheet_id,
            get_default_sheet_name, sheets_read_range,
            sheets_write_cells, sheets_list_worksheets,
        )

        combined = context.get("combined", {})
        instruction = combined.get("combined_instruction", "")
        text_lower = instruction.lower()

        # 1. 스프레드시트 ID 결정
        spreadsheet_id = None
        url_result = detect_google_url(instruction)
        if url_result and url_result[1] == "spreadsheet":
            spreadsheet_id = url_result[0]

        if not spreadsheet_id:
            spreadsheet_id = get_default_spreadsheet_id()

        if not spreadsheet_id:
            return {
                "result_text": (
                    "⚠️ 스프레드시트 ID가 없습니다.\n\n"
                    "• Google Sheets URL을 메시지에 포함하거나\n"
                    "• p5-sync-config.yaml에 spreadsheet_id 설정"
                ),
                "files": [],
            }

        # 2. 모드 판별: 읽기 vs 쓰기
        is_write = any(kw in text_lower for kw in [
            "수정", "변경", "기록", "쓰기", "업데이트", "입력",
            "write", "update", "edit",
        ])

        # 3. 시트 이름 추출 (있으면)
        sheet_name = get_default_sheet_name()
        # "시트명:범위" 패턴 감지
        sheet_match = re.search(r'시트[:\s]*([^\s,]+)', instruction)
        if sheet_match:
            sheet_name = sheet_match.group(1)

        if is_write:
            # ── 쓰기 모드 ──
            # "B5=진행중, C5=이동혁" 패턴 감지
            cell_pattern = re.compile(
                r'([A-Za-z]+\d+)\s*[=:]\s*([^,\n]+)'
            )
            matches = cell_pattern.findall(instruction)

            if not matches:
                return {
                    "result_text": (
                        "⚠️ 수정할 셀을 지정해주세요.\n\n"
                        "사용법: '시트수정 B5=진행중, C5=이동혁'\n"
                        "또는: '구글시트 수정 A1:완료'"
                    ),
                    "files": [],
                }

            updates = [{"cell": m[0].upper(), "value": m[1].strip()} for m in matches]
            send_progress(f"📊 {len(updates)}개 셀 업데이트 중...")

            count = sheets_write_cells(spreadsheet_id, sheet_name, updates)

            lines = [
                f"✅ {count}개 셀 업데이트 완료",
                f"시트: {sheet_name}",
                "",
            ]
            for upd in updates:
                lines.append(f"  {upd['cell']} = {upd['value']}")

            return {"result_text": "\n".join(lines), "files": []}

        else:
            # ── 읽기 모드 ──
            # 범위 추출 (예: "A1:D10")
            range_match = re.search(r'([A-Za-z]+\d+:[A-Za-z]+\d+)', instruction)
            cell_range = range_match.group(1) if range_match else None

            # 시트 목록 먼저 확인?
            if "시트목록" in text_lower or "탭목록" in text_lower:
                ws_list = sheets_list_worksheets(spreadsheet_id)
                return {
                    "result_text": (
                        f"📊 시트 목록 ({len(ws_list)}개)\n"
                        + "\n".join(f"  • {ws}" for ws in ws_list)
                    ),
                    "files": [],
                }

            headers, rows = sheets_read_range(
                spreadsheet_id, sheet_name, cell_range
            )

            if not headers:
                return {
                    "result_text": f"📊 시트 '{sheet_name}' 데이터가 비어 있거나 접근할 수 없습니다.",
                    "files": [],
                }

            # 테이블 포맷 (최대 15행)
            show_rows = rows[:15]
            lines = [
                f"📊 Google Sheets — {sheet_name}",
                f"━━━━━━━━━━━━━━━━━━━━",
            ]
            if cell_range:
                lines.append(f"범위: {cell_range}")

            # 헤더
            header_line = " | ".join(h[:8] for h in headers[:8])
            lines.append(f"\n{header_line}")
            lines.append("-" * min(len(header_line), 50))

            # 행들
            for row in show_rows:
                padded = row + [""] * (len(headers) - len(row))
                row_line = " | ".join(str(c)[:8] for c in padded[:8])
                lines.append(row_line)

            lines.append(f"\n총 {len(rows)}행 (표시: {len(show_rows)}행)")
            if len(headers) > 8:
                lines.append(f"총 {len(headers)}열 (표시: 8열)")

            return {"result_text": "\n".join(lines), "files": []}

    except Exception as e:
        return {
            "result_text": f"❌ Sheets 오류: {e}\n{traceback.format_exc()[-500:]}",
            "files": [],
        }


# ═══════════════════════════════════════════════════════════════
#  5. Google Docs 읽기
# ═══════════════════════════════════════════════════════════════

def run_gdoc_read(context: dict) -> dict:
    """Google Docs 문서 텍스트 읽기."""
    send_progress = context.get("send_progress", lambda x: None)
    send_progress("📝 Google Docs 문서 읽기 중...")

    try:
        from scripts.telegram.google_utils import (
            detect_google_url, docs_get_text,
            drive_list_files, get_drive_folder_id,
        )

        combined = context.get("combined", {})
        instruction = combined.get("combined_instruction", "")
        task_dir = context.get("task_dir", "")

        # 1. URL에서 doc_id 추출
        doc_id = None
        url_result = detect_google_url(instruction)
        if url_result and url_result[1] == "document":
            doc_id = url_result[0]

        # 2. URL 없으면 키워드로 검색
        if not doc_id:
            search_query = _strip_keywords(instruction, _DOC_KEYWORDS)
            search_query = re.sub(r'https?://\S+', '', search_query).strip()

            if not search_query:
                return {
                    "result_text": (
                        "📝 읽을 문서를 지정해주세요.\n\n"
                        "사용법:\n"
                        "• Google Docs URL 전송\n"
                        "• '구글문서 회의록' (문서명 키워드)"
                    ),
                    "files": [],
                }

            folder_id = get_drive_folder_id()
            results = drive_list_files(
                folder_id=folder_id,
                query=search_query,
                file_type="application/vnd.google-apps.document",
                max_results=1,
            )

            if not results:
                return {
                    "result_text": f"❌ '{search_query}' Google Docs를 찾을 수 없습니다.",
                    "files": [],
                }

            doc_id = results[0]["id"]
            send_progress(f"📝 '{results[0]['name']}' 읽기 중...")

        # 3. 텍스트 추출
        text = docs_get_text(doc_id)
        if text is None:
            return {
                "result_text": (
                    "❌ 문서를 읽을 수 없습니다.\n"
                    "서비스 계정에 문서 접근 권한이 있는지 확인하세요."
                ),
                "files": [],
            }

        if not text.strip():
            return {
                "result_text": "📝 문서가 비어있습니다.",
                "files": [],
            }

        # 4. 텍스트 길이에 따라 처리
        result_files = []
        if len(text) > 4000:
            # 파일로 저장
            save_dir = task_dir or os.path.join(
                str(Path(__file__).resolve().parent.parent.parent),
                "telegram_data", "tasks", "temp"
            )
            os.makedirs(save_dir, exist_ok=True)
            txt_path = os.path.join(save_dir, "document_content.txt")
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(text)
            result_files.append(txt_path)

            preview = text[:2000] + f"\n\n... (전체 {len(text)}자, 파일로 저장됨)"
        else:
            preview = text

        return {
            "result_text": f"📝 Google Docs 내용\n━━━━━━━━━━━━━━━━━━━━\n\n{preview}",
            "files": result_files,
        }

    except Exception as e:
        return {
            "result_text": f"❌ Docs 읽기 오류: {e}\n{traceback.format_exc()[-500:]}",
            "files": [],
        }


# ─── 로거 초기화 ─────────────────────────────────────────────
import logging
log = logging.getLogger(__name__)
