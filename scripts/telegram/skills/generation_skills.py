#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
생성 스킬 모듈

- excel_report: 이슈 현황 엑셀 보고서 생성
- ppt_generate: 발표자료 생성 (Phase 3 stub)
- pdf_summary: PDF 요약 보고서 생성 (Phase 3 stub)
"""

from __future__ import annotations

import os
import traceback
from datetime import datetime
from typing import Any, Dict, List, Optional

from scripts.telegram.skill_utils import (
    load_vault_issues,
    create_excel_workbook,
    truncate_text,
    PRIORITY_URGENCY,
    CATEGORY_IMPACT,
)


# ═══════════════════════════════════════════════════════════════
#  excel_report — 엑셀 보고서
# ═══════════════════════════════════════════════════════════════

def run_excel_report(context: dict) -> dict:
    """
    이슈 현황 엑셀 보고서 자동 생성.

    1. 볼트 이슈 로딩
    2. 보고서 유형 파악 (이슈현황 / 카테고리별 / 담당자별)
    3. Excel 파일 생성 (COM 또는 openpyxl)
    """
    send_progress = context.get("send_progress", lambda x: None)
    combined = context.get("combined", {})
    task_dir = context.get("task_dir", ".")
    instruction = combined.get("combined_instruction", "")

    send_progress("📊 엑셀 보고서 생성 중...")

    # 이슈 로딩
    all_issues = load_vault_issues()
    if not all_issues:
        return {
            "result_text": "⚠️ 볼트에 등록된 이슈가 없어 보고서를 생성할 수 없습니다.",
            "files": [],
        }

    # 보고서 유형 파악
    report_type = _detect_report_type(instruction)
    date_str = datetime.now().strftime("%Y%m%d")

    send_progress(f"📊 {report_type} 보고서 생성 중... (이슈 {len(all_issues)}건)")

    # 시트 데이터 구성
    sheets_data = _build_report_sheets(all_issues, report_type)

    # 파일 생성
    filename = f"P5_이슈현황보고서_{date_str}.xlsx"
    output_path = os.path.join(task_dir, filename)

    result_path = create_excel_workbook(sheets_data, output_path, use_com=True)

    if result_path:
        return {
            "result_text": (
                f"✅ 엑셀 보고서 생성 완료!\n\n"
                f"📊 보고서: {filename}\n"
                f"📋 유형: {report_type}\n"
                f"📌 이슈 수: {len(all_issues)}건\n"
                f"📑 시트: {', '.join(sheets_data.keys())}"
            ),
            "files": [result_path],
        }
    else:
        return {
            "result_text": "❌ 엑셀 파일 생성에 실패했습니다. Excel/openpyxl 환경을 확인하세요.",
            "files": [],
        }


def _detect_report_type(instruction: str) -> str:
    """보고서 유형 감지."""
    inst_lower = instruction.lower()
    if any(kw in inst_lower for kw in ["카테고리", "분류별", "유형별"]):
        return "카테고리별"
    if any(kw in inst_lower for kw in ["담당", "담당자", "배정"]):
        return "담당자별"
    if any(kw in inst_lower for kw in ["미결", "미해결", "오픈", "open"]):
        return "미결이슈"
    return "전체현황"


def _build_report_sheets(
    issues: List[Dict], report_type: str
) -> Dict[str, tuple]:
    """보고서 시트 데이터 구성."""
    sheets = {}

    # 공통 헤더
    headers = [
        "이슈ID", "제목", "카테고리", "우선순위",
        "상태", "담당자", "마감일", "생성일",
    ]

    # 시트 1: 전체 이슈 현황
    rows = []
    for issue in _sort_issues(issues):
        rows.append([
            issue.get("issue_id", ""),
            issue.get("title", ""),
            issue.get("category", ""),
            issue.get("priority", ""),
            issue.get("status", ""),
            issue.get("owner", ""),
            issue.get("due_date", ""),
            issue.get("created", ""),
        ])
    sheets["전체현황"] = (headers, rows)

    # 보고서 유형별 추가 시트
    if report_type in ("카테고리별", "전체현황"):
        sheets.update(_build_category_sheet(issues, headers))

    if report_type in ("담당자별", "전체현황"):
        sheets.update(_build_owner_sheet(issues, headers))

    if report_type == "미결이슈":
        open_issues = [
            i for i in issues
            if i.get("status", "").lower() not in ("closed", "resolved", "완료")
        ]
        rows = []
        for issue in _sort_issues(open_issues):
            rows.append([
                issue.get("issue_id", ""),
                issue.get("title", ""),
                issue.get("category", ""),
                issue.get("priority", ""),
                issue.get("status", ""),
                issue.get("owner", ""),
                issue.get("due_date", ""),
                issue.get("created", ""),
            ])
        sheets["미결이슈"] = (headers, rows)

    # 요약 시트
    sheets["요약"] = _build_summary_sheet(issues)

    return sheets


def _build_category_sheet(
    issues: List[Dict], headers: List[str]
) -> Dict[str, tuple]:
    """카테고리별 시트 구성."""
    categories: Dict[str, List[Dict]] = {}
    for issue in issues:
        cat = issue.get("category", "미분류")
        categories.setdefault(cat, []).append(issue)

    result = {}
    for cat, cat_issues in sorted(categories.items()):
        sheet_name = f"분류_{cat}"[:31]
        rows = []
        for issue in _sort_issues(cat_issues):
            rows.append([
                issue.get("issue_id", ""),
                issue.get("title", ""),
                issue.get("category", ""),
                issue.get("priority", ""),
                issue.get("status", ""),
                issue.get("owner", ""),
                issue.get("due_date", ""),
                issue.get("created", ""),
            ])
        result[sheet_name] = (headers, rows)

    return result


def _build_owner_sheet(
    issues: List[Dict], headers: List[str]
) -> Dict[str, tuple]:
    """담당자별 시트 구성."""
    owners: Dict[str, List[Dict]] = {}
    for issue in issues:
        owner = issue.get("owner", "미지정")
        owners.setdefault(owner, []).append(issue)

    result = {}
    for owner, owner_issues in sorted(owners.items()):
        sheet_name = f"담당_{owner}"[:31]
        rows = []
        for issue in _sort_issues(owner_issues):
            rows.append([
                issue.get("issue_id", ""),
                issue.get("title", ""),
                issue.get("category", ""),
                issue.get("priority", ""),
                issue.get("status", ""),
                issue.get("owner", ""),
                issue.get("due_date", ""),
                issue.get("created", ""),
            ])
        result[sheet_name] = (headers, rows)

    return result


def _build_summary_sheet(issues: List[Dict]) -> tuple:
    """요약 시트 데이터."""
    # 우선순위별 통계
    priority_counts: Dict[str, int] = {}
    status_counts: Dict[str, int] = {}
    category_counts: Dict[str, int] = {}

    for issue in issues:
        prio = issue.get("priority", "미분류")
        priority_counts[prio] = priority_counts.get(prio, 0) + 1

        status = issue.get("status", "미분류")
        status_counts[status] = status_counts.get(status, 0) + 1

        cat = issue.get("category", "미분류")
        category_counts[cat] = category_counts.get(cat, 0) + 1

    headers = ["구분", "항목", "건수"]
    rows = []

    rows.append(["전체", "총 이슈", len(issues)])
    rows.append(["", "", ""])

    for prio, count in sorted(priority_counts.items()):
        rows.append(["우선순위", prio, count])
    rows.append(["", "", ""])

    for status, count in sorted(status_counts.items()):
        rows.append(["상태", status, count])
    rows.append(["", "", ""])

    for cat, count in sorted(category_counts.items()):
        rows.append(["카테고리", cat, count])

    return (headers, rows)


def _sort_issues(issues: List[Dict]) -> List[Dict]:
    """이슈를 우선순위 → 마감일 순으로 정렬."""
    priority_order = {"critical": 0, "high": 1, "medium": 2, "normal": 3, "low": 4}
    return sorted(
        issues,
        key=lambda x: (
            priority_order.get(x.get("priority", "medium").lower(), 5),
            x.get("due_date", "9999-12-31"),
        ),
    )


# ═══════════════════════════════════════════════════════════════
#  ppt_generate — 발표자료 생성 (Phase 3 stub)
# ═══════════════════════════════════════════════════════════════

def run_ppt_generate(context: dict) -> dict:
    """발표자료 생성 (Phase 3에서 본격 구현 예정)."""
    return {
        "result_text": (
            "🔜 PPT 발표자료 생성 스킬은 Phase 3에서 구현 예정입니다.\n\n"
            "계획 기능:\n"
            "• 주간회의 보고 PPT 자동 생성\n"
            "• 이슈 현황 + 리스크 매트릭스 슬라이드\n"
            "• 일정 현황 요약 슬라이드\n\n"
            "현재 대안: \"엑셀보고서\" 스킬로 이슈 현황 보고서 생성 가능"
        ),
        "files": [],
    }


# ═══════════════════════════════════════════════════════════════
#  pdf_summary — PDF 요약 보고서 (Phase 3 stub)
# ═══════════════════════════════════════════════════════════════

def run_pdf_summary(context: dict) -> dict:
    """PDF 요약 보고서 생성 (Phase 3에서 본격 구현 예정)."""
    return {
        "result_text": (
            "🔜 PDF 요약 보고서 생성 스킬은 Phase 3에서 구현 예정입니다.\n\n"
            "계획 기능:\n"
            "• 이슈 요약 PDF 보고서\n"
            "• 주간 현황 PDF 생성\n"
            "• 리스크 매트릭스 PDF 출력"
        ),
        "files": [],
    }
