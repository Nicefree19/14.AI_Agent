#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
유틸리티 스킬 모듈

- skill_help: 도움말 (스킬 목록)
- issue_lookup: 이슈 조회 (SEN-XXX 또는 키워드)
- file_convert: 파일 변환 (PDF↔이미지, Excel→PDF)
- quick_calc: 빠른 계산 (Phase 3 stub)
"""

from __future__ import annotations

import os
import re
import traceback
from typing import Dict, List

from scripts.telegram.skills_registry import get_skill_help_text
from scripts.telegram.skill_utils import (
    detect_sen_refs,
    search_issues,
    get_issue_by_id,
    format_issue_detail,
    extract_files_by_ext,
    get_file_path,
    render_pdf_page,
    truncate_text,
)


# ═══════════════════════════════════════════════════════════════
#  skill_help — 도움말
# ═══════════════════════════════════════════════════════════════

def run_skill_help(context: dict) -> dict:
    """사용 가능한 스킬 목록 표시."""
    help_text = get_skill_help_text()
    return {"result_text": help_text, "files": []}


# ═══════════════════════════════════════════════════════════════
#  issue_lookup — 이슈 조회
# ═══════════════════════════════════════════════════════════════

def run_issue_lookup(context: dict) -> dict:
    """
    P5 이슈를 SEN-XXX ID 또는 키워드로 검색.

    지시 텍스트에서:
    1. SEN-XXX 패턴 감지 → 특정 이슈 상세 조회
    2. 키워드 → 전문 검색 상위 5개
    """
    send_progress = context.get("send_progress", lambda x: None)
    combined = context.get("combined", {})
    instruction = combined.get("combined_instruction", "")

    send_progress("🔍 이슈 검색 중...")

    # 1. SEN-XXX 패턴 감지
    sen_refs = detect_sen_refs(instruction)
    if sen_refs:
        results = []
        for ref in sen_refs[:5]:  # 최대 5개
            issue = get_issue_by_id(ref)
            if issue:
                results.append(format_issue_detail(issue))
            else:
                results.append(f"⚠️ {ref}: 해당 이슈를 찾을 수 없습니다.")

        return {
            "result_text": "\n\n".join(results),
            "files": [],
        }

    # 2. 키워드 추출 (이슈조회, 이슈검색, 조회 키워드 제거 후 나머지)
    keyword = instruction
    for remove_kw in ["이슈조회", "이슈검색", "조회", "검색", "이슈", "issue", "lookup", "search"]:
        keyword = keyword.replace(remove_kw, "")
    keyword = keyword.strip()

    if not keyword:
        # 키워드 없으면 최근 이슈 5개
        from scripts.telegram.skill_utils import load_vault_issues
        all_issues = load_vault_issues()
        if not all_issues:
            return {
                "result_text": "📋 등록된 이슈가 없습니다.\n\n사용법: \"SEN-070 조회\" 또는 \"이슈조회 PSRC\"",
                "files": [],
            }
        # 우선순위 높은 순
        priority_order = {"critical": 0, "high": 1, "medium": 2, "normal": 3, "low": 4}
        sorted_issues = sorted(
            all_issues,
            key=lambda x: priority_order.get(x.get("priority", "medium").lower(), 5),
        )
        lines = ["📋 최근 주요 이슈 (상위 5개)", "━" * 30, ""]
        for issue in sorted_issues[:5]:
            iid = issue.get("issue_id", "?")
            title = issue.get("title", "제목 없음")
            prio = issue.get("priority", "?")
            status = issue.get("status", "?")
            lines.append(f"• {iid}: {title}")
            lines.append(f"  우선순위: {prio} | 상태: {status}")
            lines.append("")

        lines.append("💡 \"SEN-070 조회\" 또는 \"이슈조회 PSRC\" 형태로 검색 가능")
        return {"result_text": "\n".join(lines), "files": []}

    # 3. 키워드 검색
    matches = search_issues(keyword, max_results=5)
    if not matches:
        return {
            "result_text": f"🔍 \"{keyword}\" 관련 이슈를 찾을 수 없습니다.\n\n다른 키워드로 시도해 보세요.",
            "files": [],
        }

    lines = [f"🔍 \"{keyword}\" 검색 결과 ({len(matches)}건)", "━" * 30, ""]
    for issue in matches:
        lines.append(format_issue_detail(issue))
        lines.append("")

    return {"result_text": truncate_text("\n".join(lines)), "files": []}


# ═══════════════════════════════════════════════════════════════
#  file_convert — 파일 변환
# ═══════════════════════════════════════════════════════════════

def run_file_convert(context: dict) -> dict:
    """
    파일 포맷 변환.

    지원:
    - PDF → PNG 이미지 (각 페이지)
    - Excel → 텍스트 요약 (openpyxl)
    """
    send_progress = context.get("send_progress", lambda x: None)
    combined = context.get("combined", {})
    task_dir = context.get("task_dir", ".")
    instruction = combined.get("combined_instruction", "").lower()

    send_progress("🔄 파일 변환 중...")

    # PDF 변환
    pdf_files = extract_files_by_ext(context, [".pdf"])
    if pdf_files:
        return _convert_pdf_to_images(pdf_files, task_dir)

    # Excel 파일 확인
    excel_files = extract_files_by_ext(context, [".xlsx", ".xls", ".csv"])
    if excel_files:
        return _convert_excel_info(excel_files, task_dir)

    return {
        "result_text": (
            "⚠️ 변환할 파일이 첨부되지 않았습니다.\n\n"
            "지원 변환:\n"
            "• PDF → 이미지 (PNG)\n"
            "• Excel/CSV → 데이터 요약"
        ),
        "files": [],
    }


def _convert_pdf_to_images(
    pdf_files: List[Dict], task_dir: str
) -> dict:
    """PDF의 각 페이지를 PNG로 변환."""
    output_files = []
    messages = []

    for finfo in pdf_files[:3]:  # 최대 3개 PDF
        fpath = get_file_path(finfo, task_dir)
        if not fpath:
            messages.append(f"⚠️ {finfo.get('name', '?')}: 파일을 찾을 수 없습니다.")
            continue

        try:
            import fitz
            doc = fitz.open(fpath)
            page_count = min(len(doc), 10)  # 최대 10페이지
            fname = os.path.splitext(os.path.basename(fpath))[0]

            for i in range(page_count):
                img_path = render_pdf_page(fpath, page=i, dpi=200)
                if img_path:
                    output_files.append(img_path)

            messages.append(f"✅ {finfo.get('name', '?')}: {page_count}페이지 → PNG 변환 완료")
            doc.close()

        except ImportError:
            messages.append("⚠️ pymupdf가 설치되지 않아 PDF 변환 불가")
        except Exception as e:
            messages.append(f"❌ {finfo.get('name', '?')}: 변환 오류 - {e}")

    return {
        "result_text": "\n".join(messages) if messages else "✅ 변환 완료",
        "files": output_files,
    }


def _convert_excel_info(
    excel_files: List[Dict], task_dir: str
) -> dict:
    """Excel 파일 기본 정보 추출."""
    messages = []

    for finfo in excel_files[:3]:
        fpath = get_file_path(finfo, task_dir)
        if not fpath:
            messages.append(f"⚠️ {finfo.get('name', '?')}: 파일을 찾을 수 없습니다.")
            continue

        try:
            import pandas as pd
            ext = os.path.splitext(fpath)[1].lower()

            if ext == ".csv":
                df = pd.read_csv(fpath, nrows=100)
                messages.append(f"📊 {finfo.get('name')}: CSV {df.shape[0]}행 × {df.shape[1]}열")
            else:
                xls = pd.ExcelFile(fpath, engine="openpyxl")
                for sheet in xls.sheet_names[:5]:
                    df = pd.read_excel(xls, sheet_name=sheet, nrows=100)
                    messages.append(f"📊 {finfo.get('name')} [{sheet}]: {df.shape[0]}행 × {df.shape[1]}열")

        except Exception as e:
            messages.append(f"❌ {finfo.get('name', '?')}: 읽기 오류 - {e}")

    return {"result_text": "\n".join(messages), "files": []}


# ═══════════════════════════════════════════════════════════════
#  quick_calc — 빠른 계산 (Phase 3 stub)
# ═══════════════════════════════════════════════════════════════

def run_quick_calc(context: dict) -> dict:
    """빠른 계산 (Phase 3에서 본격 구현 예정)."""
    return {
        "result_text": (
            "🔜 빠른 계산 스킬은 Phase 3에서 구현 예정입니다.\n\n"
            "계획 기능:\n"
            "• 날짜 차이 계산 (공기 계산)\n"
            "• 수량 합계/평균\n"
            "• 부재 수량 비교"
        ),
        "files": [],
    }
