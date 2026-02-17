#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
분석 스킬 모듈

- pdf_analyze: PDF 텍스트 추출 + 구조 분석
- drawing_analyze: 도면 정밀 분석 (Zone 기반 다중 프롬프트 OCR + DXF 직접 파싱)
- excel_analyze: 엑셀/CSV 데이터 요약 분석
"""

from __future__ import annotations

import logging
import os
import traceback
from pathlib import Path
from typing import Dict, List

from scripts.telegram.skill_utils import (
    extract_files_by_ext,
    get_file_path,
    extract_pdf_text,
    render_pdf_page,
    detect_pdf_structure,
    detect_sen_refs,
    detect_drawing_refs,
    search_issues,
    get_issue_by_id,
    format_issue_detail,
    truncate_text,
    save_text_to_file,
)

log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
#  pdf_analyze — PDF 분석
# ═══════════════════════════════════════════════════════════════

def run_pdf_analyze(context: dict) -> dict:
    """
    PDF 문서 텍스트 추출 및 구조 분석.

    1. 첨부 PDF에서 텍스트 추출
    2. 구조 감지 (헤더, 표, 목록)
    3. 도면번호/SEN 이슈 교차 참조
    4. 추출 텍스트를 파일로 저장
    """
    send_progress = context.get("send_progress", lambda x: None)
    task_dir = context.get("task_dir", ".")

    send_progress("📄 PDF 분석 중...")

    # PDF 파일 추출
    pdf_files = extract_files_by_ext(context, [".pdf"])
    if not pdf_files:
        return {
            "result_text": "⚠️ PDF 파일이 첨부되지 않았습니다.\nPDF 파일을 보내면 자동으로 분석합니다.",
            "files": [],
        }

    results: List[str] = []
    output_files: List[str] = []

    for idx, finfo in enumerate(pdf_files[:3]):  # 최대 3개 PDF
        fname = finfo.get("name", f"file_{idx}.pdf")
        fpath = get_file_path(finfo, task_dir)

        if not fpath:
            results.append(f"⚠️ {fname}: 파일을 찾을 수 없습니다.")
            continue

        send_progress(f"📄 [{idx + 1}/{len(pdf_files[:3])}] {fname} 분석 중...")

        # 텍스트 추출
        text, total_pages = extract_pdf_text(fpath, max_pages=50)
        if not text or total_pages == 0:
            results.append(f"⚠️ {fname}: 텍스트 추출 실패")
            continue

        # 구조 분석
        structure = detect_pdf_structure(text)

        # 요약 생성
        lines = [
            f"📄 {fname} 분석 결과",
            f"━━━━━━━━━━━━━━━━━━━━━━━━",
            f"• 총 페이지: {total_pages}",
            f"• 추출 텍스트: {len(text):,}자",
        ]

        if structure["headers"]:
            lines.append(f"• 감지된 섹션: {len(structure['headers'])}개")
            for h in structure["headers"][:5]:
                lines.append(f"  → {h}")

        if structure["tables_hint"]:
            lines.append("• 📊 표 데이터 포함")
        if structure["list_items"] > 0:
            lines.append(f"• 📝 목록 항목: {structure['list_items']}개")

        # 도면번호 / SEN 참조
        drawing_refs = structure.get("drawing_refs", [])
        sen_refs = detect_sen_refs(text)

        if drawing_refs:
            lines.append(f"\n🔧 감지된 도면번호 ({len(drawing_refs)}개):")
            for ref in drawing_refs[:10]:
                lines.append(f"  • {ref}")

        if sen_refs:
            lines.append(f"\n📌 관련 SEN 이슈 ({len(sen_refs)}개):")
            for ref in sen_refs[:5]:
                issue = get_issue_by_id(ref)
                if issue:
                    lines.append(f"  • {ref}: {issue.get('title', '?')} [{issue.get('status', '?')}]")
                else:
                    lines.append(f"  • {ref}")

        # 텍스트 미리보기 (처음 500자)
        preview = text[:500].strip()
        lines.append(f"\n📝 텍스트 미리보기:\n{preview}...")

        results.append("\n".join(lines))

        # 전문 파일 저장
        txt_path = save_text_to_file(
            text, task_dir,
            f"{os.path.splitext(fname)[0]}_extracted.txt"
        )
        output_files.append(txt_path)

    return {
        "result_text": truncate_text("\n\n".join(results)),
        "files": output_files,
    }


# ═══════════════════════════════════════════════════════════════
#  drawing_analyze — 도면 분석
# ═══════════════════════════════════════════════════════════════

def run_drawing_analyze(context: dict) -> dict:
    """
    정밀 도면 분석 (Zone 기반 다중 프롬프트 OCR + DXF 직접 파싱).

    지원 파일:
    - PDF (.pdf): 고해상도 렌더링 → OpenCV 전처리 → Zone 분할 → 영역별 OCR
    - 이미지 (.png, .jpg, .jpeg): 직접 전처리 → Zone 분할 → 영역별 OCR
    - CAD (.dxf, .dwg): ezdxf 직접 파싱 (OCR 불필요)

    분석 항목:
    1. 타이틀 블록 (도면번호, 리비전, 스케일, 설계자)
    2. 치수 정보 (길이, 높이, 간격, 단면)
    3. 구조 상세 (부재, 단면, 철근, 콘크리트)
    4. 그리드 시스템 (축번호, 축간 거리)
    5. 주석/사양 (일반 노트, 특기 사양, 참조 규격)
    6. 수량 집계 (부재별 수량, 총 면적)
    7. 도면번호/SEN 이슈 교차 참조
    8. 품질 평가 (인식 신뢰도, DPI 추정)
    """
    send_progress = context.get("send_progress", lambda x: None)
    task_dir = context.get("task_dir", ".")

    send_progress("📐 도면 정밀 분석 시작...")

    # ── 파일 추출 (PDF + 이미지 + DXF) ──
    all_exts = [".pdf", ".png", ".jpg", ".jpeg", ".dxf", ".dwg"]
    drawing_files = extract_files_by_ext(context, all_exts)

    if not drawing_files:
        return {
            "result_text": (
                "⚠️ 도면 파일이 첨부되지 않았습니다.\n\n"
                "지원 형식:\n"
                "  📄 PDF (.pdf)\n"
                "  🖼️ 이미지 (.png, .jpg)\n"
                "  📐 CAD (.dxf, .dwg)\n\n"
                "도면 파일을 보내면 자동으로 정밀 분석합니다."
            ),
            "files": [],
        }

    results: List[str] = []
    output_files: List[str] = []

    for idx, finfo in enumerate(drawing_files[:3]):
        fname = finfo.get("name", f"drawing_{idx}")
        fpath = get_file_path(finfo, task_dir)

        if not fpath:
            results.append(f"⚠️ {fname}: 파일을 찾을 수 없습니다.")
            continue

        ext = os.path.splitext(fname)[1].lower()
        total = len(drawing_files[:3])

        send_progress(f"📐 [{idx + 1}/{total}] {fname} 정밀 분석 중...")

        try:
            if ext in (".dxf", ".dwg"):
                # ── DXF/DWG: 직접 파싱 (OCR 불필요) ──
                result_text, files = _analyze_dxf(
                    fpath, fname, task_dir, send_progress
                )
            elif ext == ".pdf":
                # ── PDF: 렌더링 → OCR 분석 ──
                result_text, files = _analyze_pdf_drawing(
                    fpath, fname, task_dir, send_progress
                )
            elif ext in (".png", ".jpg", ".jpeg"):
                # ── 이미지: 직접 OCR 분석 ──
                result_text, files = _analyze_image_drawing(
                    fpath, fname, task_dir, send_progress
                )
            else:
                result_text = f"⚠️ {fname}: 지원하지 않는 형식 ({ext})"
                files = []

            results.append(result_text)
            output_files.extend(files)

        except Exception as e:
            log.error("도면 분석 오류: %s - %s", fname, e, exc_info=True)
            results.append(
                f"❌ {fname} 분석 오류: {e}\n{traceback.format_exc()[-300:]}"
            )

    return {
        "result_text": truncate_text("\n\n".join(results)),
        "files": output_files,
    }


# ── 도면 분석 내부 헬퍼 ─────────────────────────────────────────


def _analyze_dxf(
    fpath: str,
    fname: str,
    task_dir: str,
    send_progress,
) -> tuple:
    """DXF/DWG 파일 직접 파싱."""
    try:
        from scripts.ocr.dxf_parser import DxfParser
    except ImportError as e:
        pkg = str(e).split("'")[-2] if "'" in str(e) else str(e)
        return f"⚠️ DXF 분석 미지원: {pkg} 패키지 필요 (`pip install {pkg}`)", []

    send_progress(f"📐 {fname}: DXF 직접 파싱 중...")

    parser = DxfParser()
    analysis = parser.parse(fpath)
    summary = parser.summarize(analysis)

    return summary, []


def _analyze_pdf_drawing(
    fpath: str,
    fname: str,
    task_dir: str,
    send_progress,
) -> tuple:
    """PDF 도면 → 이미지 렌더링 → StructuralAnalyzer."""
    try:
        from scripts.ocr.structural_analyzer import StructuralAnalyzer
        from scripts.ocr.report_generator import DrawingReportGenerator
    except ImportError as e:
        pkg = str(e).split("'")[-2] if "'" in str(e) else str(e)
        return f"⚠️ PDF 도면 분석 미지원: {pkg} 패키지 필요 (`pip install {pkg}`)", []

    output_files = []

    # PDF 텍스트 추출 (페이지 수 확인용)
    _, total_pages = extract_pdf_text(fpath, max_pages=5)

    send_progress(f"📐 {fname}: 고해상도 렌더링 중...")

    # 첫 페이지를 고해상도 이미지로 렌더링
    img_path = render_pdf_page(fpath, page=0, dpi=300)
    if not img_path:
        # fallback: 기본 DPI
        img_path = render_pdf_page(fpath, page=0, dpi=200)

    if not img_path:
        return f"⚠️ {fname}: PDF 이미지 렌더링 실패", []

    output_files.append(img_path)

    # StructuralAnalyzer로 정밀 분석
    send_progress(f"📐 {fname}: Zone 기반 정밀 분석 중...")

    analyzer = StructuralAnalyzer()
    try:
        analysis = analyzer.analyze(img_path, send_progress=send_progress)
        analysis["file_name"] = fname
        analysis["total_pages"] = total_pages

        # 리포트 생성
        reporter = DrawingReportGenerator()
        report_text = reporter.generate(analysis)

        # Excel 리포트 (선택적)
        excel_path = os.path.join(task_dir, f"{os.path.splitext(fname)[0]}_분석.xlsx")
        excel_result = reporter.generate_excel(analysis, excel_path)
        if excel_result:
            output_files.append(excel_result)

        return report_text, output_files

    finally:
        analyzer.cleanup()


def _analyze_image_drawing(
    fpath: str,
    fname: str,
    task_dir: str,
    send_progress,
) -> tuple:
    """이미지 도면 → StructuralAnalyzer 직접 분석."""
    try:
        from scripts.ocr.structural_analyzer import StructuralAnalyzer
        from scripts.ocr.report_generator import DrawingReportGenerator
    except ImportError as e:
        pkg = str(e).split("'")[-2] if "'" in str(e) else str(e)
        return f"⚠️ 이미지 도면 분석 미지원: {pkg} 패키지 필요 (`pip install {pkg}`)", []

    output_files = []

    send_progress(f"📐 {fname}: Zone 기반 정밀 분석 중...")

    analyzer = StructuralAnalyzer()
    try:
        analysis = analyzer.analyze(fpath, send_progress=send_progress)
        analysis["file_name"] = fname

        # 리포트 생성
        reporter = DrawingReportGenerator()
        report_text = reporter.generate(analysis)

        # Excel 리포트 (선택적)
        excel_path = os.path.join(task_dir, f"{os.path.splitext(fname)[0]}_분석.xlsx")
        excel_result = reporter.generate_excel(analysis, excel_path)
        if excel_result:
            output_files.append(excel_result)

        return report_text, output_files

    finally:
        analyzer.cleanup()


# ═══════════════════════════════════════════════════════════════
#  excel_analyze — 엑셀 분석
# ═══════════════════════════════════════════════════════════════

def run_excel_analyze(context: dict) -> dict:
    """
    엑셀/CSV 파일 데이터 요약 분석.

    1. 시트별 행/열 수, 컬럼 타입, 기초 통계
    2. 건설 특화 컬럼 감지 (항목, 수량, 단가, 금액, 일정)
    3. 결과 텍스트 요약
    """
    send_progress = context.get("send_progress", lambda x: None)
    task_dir = context.get("task_dir", ".")

    send_progress("📊 엑셀 분석 중...")

    excel_files = extract_files_by_ext(context, [".xlsx", ".xls", ".csv"])
    if not excel_files:
        return {
            "result_text": "⚠️ 엑셀/CSV 파일이 첨부되지 않았습니다.\n파일을 보내면 자동으로 분석합니다.",
            "files": [],
        }

    try:
        import pandas as pd
    except ImportError:
        return {
            "result_text": "⚠️ pandas가 설치되지 않아 엑셀 분석이 불가합니다.",
            "files": [],
        }

    results: List[str] = []

    for idx, finfo in enumerate(excel_files[:3]):
        fname = finfo.get("name", f"file_{idx}")
        fpath = get_file_path(finfo, task_dir)

        if not fpath:
            results.append(f"⚠️ {fname}: 파일을 찾을 수 없습니다.")
            continue

        send_progress(f"📊 [{idx + 1}/{len(excel_files[:3])}] {fname} 분석 중...")

        ext = os.path.splitext(fpath)[1].lower()

        try:
            if ext == ".csv":
                sheets = {"데이터": pd.read_csv(fpath, nrows=100000)}
            else:
                xls = pd.ExcelFile(fpath, engine="openpyxl")
                sheets = {}
                for sheet_name in xls.sheet_names[:10]:
                    sheets[sheet_name] = pd.read_excel(
                        xls, sheet_name=sheet_name, nrows=100000
                    )

        except Exception as e:
            results.append(f"❌ {fname}: 파일 읽기 오류 - {e}")
            continue

        lines = [
            f"📊 {fname} 분석 결과",
            f"━━━━━━━━━━━━━━━━━━━━━━━━",
            f"• 시트 수: {len(sheets)}",
        ]

        for sheet_name, df in sheets.items():
            lines.append(f"\n📋 시트: {sheet_name}")
            lines.append(f"  행: {df.shape[0]:,} | 열: {df.shape[1]}")

            # 컬럼 정보
            lines.append(f"  컬럼:")
            for col in df.columns[:15]:
                dtype = str(df[col].dtype)
                non_null = df[col].count()
                lines.append(f"    • {col} ({dtype}) — {non_null:,}건")

            # 건설 특화 컬럼 감지
            construction_cols = _detect_construction_columns(df)
            if construction_cols:
                lines.append(f"\n  🏗️ 건설 특화 컬럼 감지:")
                for col_type, col_name in construction_cols:
                    lines.append(f"    • {col_type}: {col_name}")

            # 수치형 기초 통계
            numeric_cols = df.select_dtypes(include=["number"]).columns
            if len(numeric_cols) > 0:
                lines.append(f"\n  📈 수치 요약:")
                for col in numeric_cols[:5]:
                    total = df[col].sum()
                    avg = df[col].mean()
                    lines.append(f"    • {col}: 합계={total:,.0f} | 평균={avg:,.1f}")

            # 행이 많으면 경고
            if df.shape[0] > 10000:
                lines.append(f"\n  ⚠️ 대용량 데이터 ({df.shape[0]:,}행) — 샘플링 분석 적용")

        results.append("\n".join(lines))

    return {
        "result_text": truncate_text("\n\n".join(results)),
        "files": [],
    }


# ─── 건설 특화 컬럼 감지 ──────────────────────────────────────

_CONSTRUCTION_COL_PATTERNS = {
    "항목/품명": ["항목", "품명", "부재", "명칭", "item", "description"],
    "수량": ["수량", "qty", "quantity", "ea", "개수"],
    "단가": ["단가", "unit price", "unit cost"],
    "금액": ["금액", "amount", "total", "소계"],
    "단위": ["단위", "unit", "규격"],
    "일정": ["일정", "납기", "예정일", "date", "schedule", "deadline"],
    "위치": ["위치", "층", "zone", "area", "floor"],
    "규격": ["규격", "size", "spec", "사양"],
}


def _detect_construction_columns(df) -> List[tuple]:
    """건설 관련 컬럼 패턴 감지."""
    found = []
    for col in df.columns:
        col_lower = str(col).lower()
        for col_type, patterns in _CONSTRUCTION_COL_PATTERNS.items():
            if any(p in col_lower for p in patterns):
                found.append((col_type, str(col)))
                break
    return found
