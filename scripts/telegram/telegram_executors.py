#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P5 프로젝트 작업 실행기 매핑 (Executor Dispatch)

텔레그램 지시 텍스트에서 키워드를 매칭하여 적절한 P5 작업 실행기를 반환한다.

Executor 계약:
    입력: context (dict) — combined, memories, task_dir, send_progress
    출력: {"result_text": str, "files": list[str]}
"""

from __future__ import annotations

import os
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# scripts/ 디렉토리를 import path에 추가
_SCRIPTS_DIR = str(Path(__file__).resolve().parent.parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)


@dataclass
class ExecutorResult:
    """Executor 반환 데이터 클래스."""
    result_text: str
    files: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"result_text": self.result_text, "files": self.files}


def _import_error_result(module: str, symbol: str, exc: ImportError) -> dict:
    """ImportError를 모듈 없음/심볼 없음으로 구분하여 메시지 생성."""
    err_msg = str(exc)
    if "No module named" in err_msg:
        detail = f"모듈 없음: {err_msg}"
    else:
        detail = f"심볼 없음 ({symbol}): {err_msg}"
    return {"result_text": f"⚠️ {module} 로드 실패 — {detail}", "files": []}


# 키워드 → executor 이름 매핑 (순서 중요: 긴 키워드 먼저, 먼저 매칭되는 것이 우선)
KEYWORD_MAP = {
    # ── 신규 스킬: 구조 엔지니어링 (긴 키워드 먼저) ──
    "연쇄분석": "cascade_analyzer",
    "파급분석": "cascade_analyzer",
    "파급효과": "cascade_analyzer",
    "연관분석": "cascade_analyzer",
    "영향분석": "cascade_analyzer",
    "종속관계": "cascade_analyzer",
    "cascade": "cascade_analyzer",
    "방치이슈": "stale_hunter",
    "장기미결": "stale_hunter",
    "미결이슈": "stale_hunter",
    "방치탐지": "stale_hunter",
    "지연이슈": "stale_hunter",
    "에스컬레이션": "stale_hunter",
    "escalation": "stale_hunter",
    "결정기록": "decision_logger",
    "결정사항": "decision_logger",
    "의사결정": "decision_logger",
    "회의결정": "decision_logger",
    "결정등록": "decision_logger",
    "결정:": "decision_logger",
    "리드타임": "lead_time_tracker",
    "납기추적": "lead_time_tracker",
    "공정추적": "lead_time_tracker",
    "크리티컬패스": "lead_time_tracker",
    "주요경로": "lead_time_tracker",
    "일정분석": "lead_time_tracker",
    "leadtime": "lead_time_tracker",
    "협력사현황": "contractor_digest",
    "업체현황": "contractor_digest",
    "업체별": "contractor_digest",
    "협력사별": "contractor_digest",
    "삼성현황": "contractor_digest",
    "센구조현황": "contractor_digest",
    "이앤디몰현황": "contractor_digest",
    "삼우현황": "contractor_digest",
    "주간경영": "weekly_executive",
    "경영보고": "weekly_executive",
    "주간보고서": "weekly_executive",
    "주간현황": "weekly_executive",
    "위클리": "weekly_executive",
    "weekly": "weekly_executive",
    "주보": "weekly_executive",
    "사양검증": "spec_checker",
    "스펙체크": "spec_checker",
    "사양확인": "spec_checker",
    "규격검증": "spec_checker",
    "도면검증": "spec_checker",
    "speccheck": "spec_checker",
    # ── 신규 스킬: 자동화 5대 스킬 (긴 키워드 먼저) ──
    "카톡요약리포트": "kakao_daily_summary",
    "카톡일일요약": "kakao_daily_summary",
    "카톡업무요약": "kakao_daily_summary",
    "이슈트렌드": "issue_trend",
    "이슈대시보드": "issue_trend",
    "트렌드분석": "issue_trend",
    "PSRC트렌드": "issue_trend",
    "물량감시": "quantity_monitor",
    "물량변동": "quantity_monitor",
    "물량모니터": "quantity_monitor",
    "연계추적": "traceability_map",
    "추적맵": "traceability_map",
    "트레이서빌리티": "traceability_map",
    "연계분석": "traceability_map",
    "시스템점검": "health_report",
    "헬스체크": "health_report",
    "시스템현황": "health_report",
    "재전송": "resend_failed",
    "전송실패": "resend_failed",
    "미전달": "resend_failed",
    "resend": "resend_failed",
    "health": "health_report",
    # ── 카카오톡 라이브 (MCP 기반, 긴 키워드 먼저 — 기존 카톡 키워드보다 앞에!) ──
    "카톡실시간검색": "kakao_live_read",
    "카톡답변제안": "kakao_context",
    "카톡뭐라고할까": "kakao_context",
    "카톡브리핑실시간": "kakao_context",
    "카톡내보내기자동": "kakao_live_read",
    "카톡자동저장": "kakao_live_read",
    "카톡방목록": "kakao_room_list",
    "카톡방리스트": "kakao_room_list",
    "열린카톡": "kakao_room_list",
    "카톡읽기": "kakao_live_read",
    "카톡실시간": "kakao_live_read",
    "실시간카톡": "kakao_live_read",
    "카톡라이브": "kakao_live_read",
    "카톡지금": "kakao_live_read",
    "카톡보내": "kakao_reply_draft",
    "카톡전송": "kakao_reply_draft",
    "카톡입력": "kakao_reply_draft",
    "카톡맥락": "kakao_context",
    "카톡상황": "kakao_context",
    "카톡답변": "kakao_context",
    "카카오읽기": "kakao_live_read",
    "카카오실시간": "kakao_live_read",
    # ── 카카오톡 export 기반 (기존) ──
    "카톡검색": "kakao_search",
    "카카오검색": "kakao_search",
    "카톡요약": "kakao_summary",
    "카카오요약": "kakao_summary",
    "카톡답장": "kakao_summary",
    "카카오답장": "kakao_summary",
    "카톡목록": "kakao_chat",
    "카카오목록": "kakao_chat",
    "카톡확인": "kakao_chat",
    "카카오확인": "kakao_chat",
    "카톡": "kakao_chat",
    "카카오": "kakao_chat",
    "kakao": "kakao_chat",
    # ── 신규 스킬: 이메일 강화 (긴 키워드 먼저) ──
    "첨부파일분석": "email_attachment",
    "첨부파일확인": "email_attachment",
    "메일첨부분석": "email_attachment",
    "메일첨부파일": "email_attachment",
    "이메일첨부": "email_attachment",
    "첨부확인": "email_attachment",
    "첨부분석": "email_attachment",
    "첨부다운": "email_attachment",
    "이메일발송": "email_send",
    "이메일보내": "email_send",
    "이메일전송": "email_send",
    "메일발송": "email_send",
    "메일보내": "email_send",
    "메일전송": "email_send",
    "메일작성": "email_send",
    "메일회신": "email_reply",
    "메일답장": "email_reply",
    "전체회신": "email_reply",
    # ── 신규 스킬: Google 연동 (긴 키워드 먼저) ──
    "드라이브검색": "gdrive_browse",
    "드라이브목록": "gdrive_browse",
    "구글드라이브": "gdrive_browse",
    "공유폴더": "gdrive_browse",
    "드라이브다운": "gdrive_download",
    "파일다운로드": "gdrive_download",
    "메일확인": "email_check",
    "메일조회": "email_check",
    "받은메일": "email_check",
    "최근메일": "email_check",
    "시트수정": "gsheet_edit",
    "시트조회": "gsheet_edit",
    "구글시트": "gsheet_edit",
    "스프레드시트": "gsheet_edit",
    "구글문서": "gdoc_read",
    "문서읽기": "gdoc_read",
    # ── 신규 스킬: 유틸리티 (긴 키워드 먼저) ──
    "도움말": "skill_help",
    "명령어": "skill_help",
    "스킬": "skill_help",
    "help": "skill_help",
    "이슈조회": "issue_lookup",
    "이슈검색": "issue_lookup",
    "이슈확인": "issue_lookup",
    "이슈상태": "issue_lookup",
    "이슈찾기": "issue_lookup",
    "파일변환": "file_convert",
    "컨버트": "file_convert",
    "계산": "quick_calc",
    "산출": "quick_calc",
    # ── 신규 스킬: 분석 (파일 자동감지와 별도로 키워드 트리거) ──
    "pdf분석": "pdf_analyze",
    "문서분석": "pdf_analyze",
    "도서분석": "pdf_analyze",
    "pdf확인": "pdf_analyze",
    "도면정밀분석": "drawing_analyze",
    "도면분석": "drawing_analyze",
    "도면확인": "drawing_analyze",
    "shop도면": "drawing_analyze",
    "드로잉": "drawing_analyze",
    "치수분석": "drawing_analyze",
    "철근분석": "drawing_analyze",
    "단면분석": "drawing_analyze",
    "구조분석": "drawing_analyze",
    "도면정밀": "drawing_analyze",
    "블루프린트": "drawing_analyze",
    "cad분석": "drawing_analyze",
    "dxf분석": "drawing_analyze",
    "엑셀분석": "excel_analyze",
    "데이터분석": "excel_analyze",
    "boq분석": "excel_analyze",
    "엑셀확인": "excel_analyze",
    # ── 신규 스킬: 생성 (긴 키워드 먼저) ──
    "엑셀보고서": "excel_report",
    "이슈엑셀": "excel_report",
    "현황표": "excel_report",
    "엑셀생성": "excel_report",
    "발표자료": "ppt_generate",
    "프레젠테이션": "ppt_generate",
    "슬라이드": "ppt_generate",
    "ppt": "ppt_generate",
    # ── 신규 스킬: 인텔리전스 (긴 키워드 먼저) ──
    "메일답변": "email_response",
    "답변방향": "email_response",
    "답신": "email_reply",
    "답장": "email_reply",
    "회신": "email_reply",
    "제작현황": "fabrication_status",
    "납품현황": "fabrication_status",
    "부재현황": "fabrication_status",
    "제작상태": "fabrication_status",
    # ── 회의록 이슈 연동 (긴 키워드 먼저, "회의준비" 앞에 배치) ──
    "회의록정리": "meeting_transcript",
    "회의록분석": "meeting_transcript",
    "회의내용정리": "meeting_transcript",
    "미팅노트": "meeting_transcript",
    "미팅정리": "meeting_transcript",
    "통화내용정리": "meeting_transcript",
    "통화정리": "meeting_transcript",
    "회의이슈연동": "meeting_transcript",
    "회의결과정리": "meeting_transcript",
    "회의이슈": "meeting_transcript",
    "회의록": "meeting_transcript",
    "회의내용": "meeting_transcript",
    "통화내용": "meeting_transcript",
    # ── 이슈 생성 승인 ──
    "이슈생성승인": "meeting_issue_approval",
    "이슈승인": "meeting_issue_approval",
    # ── 회의 준비 (기존) ──
    "회의준비": "meeting_prep",
    "회의자료": "meeting_prep",
    "회의안건": "meeting_prep",
    "아젠다": "meeting_prep",
    # ── 기존: 일일 브리핑 ──
    "briefing": "daily_briefing",
    "브리핑": "daily_briefing",
    "일일": "daily_briefing",
    # ── 기존: 이메일 트리아지 ──
    "triage": "email_triage",
    "트리아지": "email_triage",
    "이메일": "email_triage",
    # ── 기존: OCR 파이프라인 ──
    "ocr": "ocr_pipeline",
    "스캔": "ocr_pipeline",
    # ── 기존: 이슈 동기화 ──
    "sync": "issue_sync",
    "동기화": "issue_sync",
    # ── 기존: 주간 보고서 ──
    "report": "weekly_report",
    "보고서": "weekly_report",
    "주간": "weekly_report",
    # ── 기존: 메트릭스 ──
    "metric": "metrics",
    "메트릭": "metrics",
    "현황": "metrics",
    "대시보드": "metrics",
    "이슈현황": "metrics",
    "리스크": "metrics",
    # ── 기존: 복합 명령 (composite) ── (긴 키워드 먼저 배치)
    "아침루틴": "morning_routine",
    "morning": "morning_routine",
    "마감점검": "closing_check",
    "전체점검": "full_check",
    "아침": "morning_routine",
    "점검": "full_check",
    "마감": "closing_check",
    # ── 데스크톱 원격 제어 (긴 키워드 먼저 — 자연어 동의어보다 앞에 배치) ──
    "활성프로그램": "desktop_control",
    "열린프로그램": "desktop_control",
    "프로그램목록": "desktop_control",
    "프로그램실행": "desktop_control",
    "프로그램열어": "desktop_control",
    "화면캡처": "desktop_control",
    "스크린샷": "desktop_control",
    "screenshot": "desktop_control",
    "화면보여": "desktop_control",
    "화면확인": "desktop_control",
    "데스크톱": "desktop_control",
    "아웃룩열어": "desktop_control",
    "크롬열어": "desktop_control",
    "엑셀열어": "desktop_control",
    "앱실행": "desktop_control",
    "앱열어": "desktop_control",
    "원격제어": "desktop_control",
    "원격조작": "desktop_control",
    "pc제어": "desktop_control",
    "pc컨트롤": "desktop_control",
    "pc화면": "desktop_control",
    "클릭해": "desktop_control",
    "입력해줘": "desktop_control",
    "작업관리자": "desktop_control",
    "시스템정보": "desktop_control",
    "지금뭐열려": "desktop_control",
    # ── 자연어 동의어 확장 (CLI 폴백 감소 — 짧은 키워드, 최후순위) ──
    "스케줄": "lead_time_tracker",
    "일정": "lead_time_tracker",
    "공정": "lead_time_tracker",
    "이슈": "issue_lookup",
    "업체": "contractor_digest",
    "검색": "email_triage",
    "pdf": "pdf_analyze",
    "요약": "meeting_prep",
    "상태": "metrics",
}


def _run_briefing(context: dict) -> dict:
    """p5_daily_briefing.py 래핑 — 일일 브리핑 생성 (cmd_generate 호출)."""
    send_progress = context.get("send_progress", lambda x: None)
    send_progress("📊 일일 브리핑 생성 중...")

    try:
        from p5_daily_briefing import cmd_generate
    except ImportError as e:
        return _import_error_result("p5_daily_briefing", "cmd_generate", e)

    try:
        import argparse
        from datetime import datetime as _dt

        args = argparse.Namespace(window=24, stdout=False, push=False, command="generate")
        cmd_generate(args)

        # cmd_generate가 생성한 파일 읽기
        today = _dt.now().strftime("%Y-%m-%d")
        briefing_path = (
            Path(_SCRIPTS_DIR).parent
            / "ResearchVault" / "P5-Project" / "00-Overview"
            / f"데일리브리핑-{today}.md"
        )
        if briefing_path.exists():
            content = briefing_path.read_text(encoding="utf-8")
            if content.startswith("---"):
                parts = content.split("---", 2)
                result_text = parts[2].strip() if len(parts) >= 3 else content
            else:
                result_text = content
            return {"result_text": result_text[:4000], "files": [str(briefing_path)]}

        return {"result_text": "📊 일일 브리핑이 생성되었습니다.", "files": []}

    except Exception as e:
        return {
            "result_text": f"❌ 브리핑 생성 오류: {e}\n{traceback.format_exc()[-500:]}",
            "files": [],
        }


def _run_triage(context: dict) -> dict:
    """p5_email_triage.py 래핑 — 이메일 트리아지 실행 (cmd_process 호출)."""
    send_progress = context.get("send_progress", lambda x: None)
    send_progress("📊 이메일 트리아지 실행 중...")

    try:
        from p5_email_triage import cmd_process
    except ImportError as e:
        return _import_error_result("p5_email_triage", "cmd_process", e)

    try:
        import argparse

        args = argparse.Namespace(
            mail_dir=None, dry_run=False, auto_apply_above=None, command="process",
        )
        cmd_process(args)

        return {"result_text": "📊 이메일 트리아지가 완료되었습니다.", "files": []}

    except Exception as e:
        return {
            "result_text": f"❌ 트리아지 오류: {e}\n{traceback.format_exc()[-500:]}",
            "files": [],
        }


def _run_ocr(context: dict) -> dict:
    """p5_ocr_pipeline.py 래핑 — OCR 처리 (cmd_process 호출)."""
    send_progress = context.get("send_progress", lambda x: None)
    send_progress("📊 OCR 파이프라인 실행 중...")

    try:
        from p5_ocr_pipeline import cmd_process as ocr_cmd_process
    except ImportError as e:
        return _import_error_result("p5_ocr_pipeline", "cmd_process", e)

    try:
        import argparse

        args = argparse.Namespace(limit=50, force=False, command="process")
        ocr_cmd_process(args)

        return {
            "result_text": "📊 OCR 파이프라인 처리가 완료되었습니다.",
            "files": [],
        }

    except Exception as e:
        return {
            "result_text": f"❌ OCR 오류: {e}\n{traceback.format_exc()[-500:]}",
            "files": [],
        }


def _run_sync(context: dict) -> dict:
    """p5_issue_sync.py 래핑 — 이슈 동기화 (cmd_sync 호출)."""
    send_progress = context.get("send_progress", lambda x: None)
    send_progress("📊 이슈 동기화 실행 중...")

    try:
        from p5_issue_sync import cmd_sync
    except ImportError as e:
        return _import_error_result("p5_issue_sync", "cmd_sync", e)

    try:
        import argparse

        args = argparse.Namespace(csv=None, debug=False, command="sync")
        cmd_sync(args)

        return {"result_text": "📊 이슈 동기화가 완료되었습니다.", "files": []}

    except Exception as e:
        return {
            "result_text": f"❌ 동기화 오류: {e}\n{traceback.format_exc()[-500:]}",
            "files": [],
        }


def _run_report(context: dict) -> dict:
    """
    주간 보고서 생성 — 메트릭 대시보드 + 주간 예외 보고서 통합.
    """
    send_progress = context.get("send_progress", lambda x: None)
    generated_files = []
    errors = []

    # ── 1단계: 운영 메트릭 대시보드 생성 ──
    send_progress("📊 [1/2] 운영 메트릭 생성 중...")
    try:
        from p5_metrics import cmd_generate as metrics_generate
        import argparse

        metrics_args = argparse.Namespace(stdout=False, command="generate")
        metrics_generate(metrics_args)

        metrics_path = Path(_SCRIPTS_DIR).parent / "ResearchVault" / "P5-Project" / "00-Overview" / "운영메트릭.md"
        if metrics_path.exists():
            generated_files.append(str(metrics_path))
    except Exception as e:
        errors.append(f"메트릭: {e}")

    # ── 2단계: 주간 예외 보고서 생성 ──
    send_progress("📊 [2/2] 주간 예외 보고서 생성 중...")
    try:
        from p5_email_triage import cmd_report as triage_report
        import argparse

        report_args = argparse.Namespace(command="report")
        triage_report(report_args)

        report_path = Path(_SCRIPTS_DIR).parent / "ResearchVault" / "P5-Project" / "00-Overview" / "주간예외보고서.md"
        if report_path.exists():
            generated_files.append(str(report_path))
    except Exception as e:
        errors.append(f"보고서: {e}")

    # ── 3단계: 요약 텍스트 구성 ──
    summary_parts = []

    # 메트릭 요약 읽기
    try:
        metrics_path = Path(_SCRIPTS_DIR).parent / "ResearchVault" / "P5-Project" / "00-Overview" / "운영메트릭.md"
        if metrics_path.exists():
            content = metrics_path.read_text(encoding="utf-8")
            # 핵심 지표 테이블 추출 (| 지표 | 상태 | 값 | 행들)
            table_lines = [
                line for line in content.split("\n")
                if line.startswith("| ") and "지표" not in line and "---" not in line
            ]
            if table_lines:
                summary_parts.append("📊 **운영 메트릭**")
                for line in table_lines[:6]:
                    # "| 이름 | 🟢 | 값 | 상세 |" → 간결하게 변환
                    cells = [c.strip() for c in line.split("|") if c.strip()]
                    if len(cells) >= 3:
                        summary_parts.append(f"  {cells[1]} {cells[0]}: {cells[2]}")
    except Exception:
        pass

    # 예외 보고서 요약 읽기
    try:
        report_path = Path(_SCRIPTS_DIR).parent / "ResearchVault" / "P5-Project" / "00-Overview" / "주간예외보고서.md"
        if report_path.exists():
            content = report_path.read_text(encoding="utf-8")
            # 액션 플랜 항목 추출
            action_lines = []
            in_action = False
            for line in content.split("\n"):
                if "액션 플랜" in line:
                    in_action = True
                    continue
                if in_action and line.startswith("##"):
                    break
                if in_action and line.strip().startswith(("1.", "2.", "3.", "4.", "5.")):
                    action_lines.append(line.strip())

            if action_lines:
                summary_parts.append("\n📋 **이번 주 액션 플랜**")
                for line in action_lines[:5]:
                    summary_parts.append(f"  {line}")

            # 데이터 품질 경고 추출
            warning_lines = []
            in_warning = False
            for line in content.split("\n"):
                if "데이터 품질 경고" in line:
                    in_warning = True
                    continue
                if in_warning and line.startswith("##"):
                    break
                if in_warning and line.strip().startswith("-"):
                    warning_lines.append(line.strip())

            if warning_lines:
                summary_parts.append("\n⚠️ **데이터 품질 경고**")
                for line in warning_lines[:5]:
                    summary_parts.append(f"  {line}")
    except Exception:
        pass

    # 최종 메시지 조합
    if summary_parts:
        result_text = "\n".join(summary_parts)
    else:
        result_text = "📊 주간 보고서가 생성되었습니다."

    if errors:
        result_text += f"\n\n⚠️ 일부 오류: {'; '.join(errors)}"

    if generated_files:
        result_text += f"\n\n📂 생성 파일: {len(generated_files)}개"

    return {"result_text": result_text, "files": generated_files}


def _run_morning_routine(context: dict) -> dict:
    """아침루틴 — 브리핑 + 메트릭 통합 조회."""
    send_progress = context.get("send_progress", lambda x: None)
    results = []
    files = []

    # 1. 일일 브리핑
    send_progress("☀️ [1/2] 일일 브리핑 생성 중...")
    try:
        r = _run_briefing(context)
        results.append(r.get("result_text", ""))
        files.extend(r.get("files", []))
    except Exception as e:
        results.append(f"❌ 브리핑 오류: {e}")

    # 2. 운영 메트릭
    send_progress("☀️ [2/2] 운영 메트릭 조회 중...")
    try:
        r = _run_metrics(context)
        results.append(r.get("result_text", ""))
        files.extend(r.get("files", []))
    except Exception as e:
        results.append(f"❌ 메트릭 오류: {e}")

    combined = "\n\n---\n\n".join(r for r in results if r)
    return {"result_text": f"☀️ **아침 루틴 완료**\n\n{combined}", "files": files}


def _run_full_check(context: dict) -> dict:
    """전체점검 — 모든 모듈 순차 실행."""
    send_progress = context.get("send_progress", lambda x: None)
    steps = [
        ("브리핑", _run_briefing),
        ("트리아지", _run_triage),
        ("동기화", _run_sync),
        ("메트릭", _run_metrics),
        ("보고서", _run_report),
    ]
    results = []
    files = []
    success = 0

    for i, (name, executor) in enumerate(steps, 1):
        send_progress(f"🔍 [{i}/{len(steps)}] {name} 실행 중...")
        try:
            r = executor(context)
            results.append(f"✅ **{name}**\n{r.get('result_text', '')[:500]}")
            files.extend(r.get("files", []))
            success += 1
        except Exception as e:
            results.append(f"❌ **{name}** 오류: {e}")

    header = f"🔍 **전체 점검 완료** ({success}/{len(steps)} 성공)\n"
    combined = "\n\n".join(results)
    return {"result_text": f"{header}\n{combined}", "files": files}


def _run_closing_check(context: dict) -> dict:
    """마감점검 — 트리아지 + 동기화 + 큐 건강도 요약."""
    send_progress = context.get("send_progress", lambda x: None)
    results = []
    files = []

    # 1. 트리아지
    send_progress("🌙 [1/3] 트리아지 실행 중...")
    try:
        r = _run_triage(context)
        results.append(r.get("result_text", ""))
        files.extend(r.get("files", []))
    except Exception as e:
        results.append(f"❌ 트리아지 오류: {e}")

    # 2. 동기화
    send_progress("🌙 [2/3] 이슈 동기화 중...")
    try:
        r = _run_sync(context)
        results.append(r.get("result_text", ""))
        files.extend(r.get("files", []))
    except Exception as e:
        results.append(f"❌ 동기화 오류: {e}")

    # 3. 큐 건강도 인라인 체크
    send_progress("🌙 [3/3] 큐 건강도 확인 중...")
    try:
        from p5_metrics import calc_queue_health
        qh = calc_queue_health()
        status_icon = {"green": "🟢", "yellow": "🟡", "red": "🔴"}.get(qh.get("status", ""), "⚪")
        results.append(f"{status_icon} **큐 건강도**: {qh['value']} ({qh['detail']})")
    except Exception as e:
        results.append(f"⚠️ 큐 건강도 확인 실패: {e}")

    combined = "\n\n".join(r for r in results if r)
    return {"result_text": f"🌙 **마감 점검 완료**\n\n{combined}", "files": files}


def _run_metrics(context: dict) -> dict:
    """p5_metrics.py 래핑 — 메트릭 현황 (개별 calc_* 함수 호출)."""
    send_progress = context.get("send_progress", lambda x: None)
    send_progress("📊 메트릭 현황 조회 중...")

    try:
        from p5_metrics import (
            calc_snr, calc_triage_accuracy, calc_decision_velocity,
            calc_queue_health, calc_data_completeness,
        )
    except ImportError as e:
        return _import_error_result("p5_metrics", "calc_*", e)

    try:
        _status_icons = {"green": "🟢", "yellow": "🟡", "red": "🔴"}
        calc_fns = [
            calc_snr, calc_triage_accuracy, calc_decision_velocity,
            calc_queue_health, calc_data_completeness,
        ]
        lines = ["📊 **P5 운영 메트릭 현황**\n"]
        for fn in calc_fns:
            try:
                m = fn()
                icon = _status_icons.get(m.get("status", ""), "⚪")
                lines.append(f"{icon} **{m.get('name', '?')}**: {m.get('value', 'N/A')}")
                if m.get("detail"):
                    lines.append(f"   {m['detail']}")
            except Exception:
                pass

        if len(lines) <= 1:
            return {"result_text": "⚠️ 메트릭을 계산할 수 없습니다.", "files": []}

        return {"result_text": "\n".join(lines), "files": []}

    except Exception as e:
        return {
            "result_text": f"❌ 메트릭 오류: {e}\n{traceback.format_exc()[-500:]}",
            "files": [],
        }


def _find_claude_cli() -> Optional[str]:
    """Claude CLI 실행 파일 탐지 (p5_autoexecutor.bat와 동일 탐색 순서).

    Returns:
        Claude CLI 경로 문자열, 또는 None.
    """
    import shutil

    # 1. User local bin (npm global install on Windows)
    user_local = os.path.join(
        os.environ.get("USERPROFILE", ""), ".local", "bin", "claude.exe"
    )
    if os.path.exists(user_local):
        return user_local

    # 2. PATH 검색
    found = shutil.which("claude") or shutil.which("claude.cmd")
    if found:
        return found

    # 3. npm global directory
    npm_global = os.path.join(
        os.environ.get("APPDATA", ""), "npm", "claude.cmd"
    )
    if os.path.exists(npm_global):
        return npm_global

    return None


def _run_claude_cli(context: dict) -> dict:
    """키워드 미매칭 지시를 Claude CLI에 위임.

    Args:
        context: 표준 executor context (combined, memories, task_dir, send_progress)

    Returns:
        {"result_text": str, "files": list[str]}
    """
    import subprocess

    send_progress = context.get("send_progress", lambda x: None)
    combined = context["combined"]
    instruction = combined["combined_instruction"]
    task_dir = context.get("task_dir", "")

    send_progress("Claude CLI로 작업을 처리합니다...")

    claude_exe = _find_claude_cli()
    if not claude_exe:
        return {
            "result_text": (
                "Claude CLI를 찾을 수 없습니다.\n\n"
                "설치: npm install -g @anthropic-ai/claude-code"
            ),
            "files": [],
        }

    # 시스템 프롬프트 파일
    project_root = Path(__file__).resolve().parent.parent.parent
    spf = project_root / "scripts" / "CLAUDE_TELEGRAM.md"
    if not spf.exists():
        spf = project_root / "CLAUDE.md"

    prompt = (
        f"Process this Telegram task. The user sent:\n\n"
        f"{instruction}\n\n"
        f"Working directory: {task_dir}\n"
        f"Report results concisely in Korean."
    )

    cmd = [str(claude_exe), "-p", "--dangerously-skip-permissions"]
    if spf.exists():
        cmd.extend(["--append-system-prompt-file", str(spf)])

    try:
        result = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=600,
            cwd=str(task_dir) if task_dir and Path(task_dir).is_dir() else str(project_root),
            encoding="utf-8",
        )

        output = result.stdout.strip()
        if result.returncode != 0 and not output:
            output = f"Claude CLI 실행 오류 (exit code {result.returncode})"
            if result.stderr:
                output += f"\n{result.stderr[:500]}"

        if not output:
            output = "작업이 완료되었으나 출력이 없습니다."

        # task_dir 내 생성된 파일 수집
        generated_files = []
        if task_dir and os.path.isdir(task_dir):
            for fname in os.listdir(task_dir):
                fpath = os.path.join(task_dir, fname)
                if os.path.isfile(fpath) and fname != "task_info.txt":
                    generated_files.append(fpath)

        return {
            "result_text": output[:4000],
            "files": generated_files,
        }

    except subprocess.TimeoutExpired:
        return {
            "result_text": "Claude CLI 실행 시간 초과 (10분).",
            "files": [],
        }
    except Exception as e:
        return {
            "result_text": f"Claude CLI 오류: {e}\n{traceback.format_exc()[-500:]}",
            "files": [],
        }


def _run_desktop_control_legacy(context: dict) -> dict:
    """데스크톱 원격 제어 — Claude CLI에 MCP 도구 안내와 함께 위임 (legacy fallback).

    Windows Controller MCP와 Claude in Chrome MCP를 활용하여
    PC 화면 상태 파악, 프로그램 제어, 스크린샷 캡처 등을 수행한다.

    내부적으로 Claude CLI 서브프로세스를 실행하며, 데스크톱 전용 프롬프트에
    사용 가능한 MCP 도구 목록, 사용법, 안전 규칙을 포함시킨다.

    Args:
        context: 표준 executor context (combined, memories, task_dir, send_progress)

    Returns:
        {"result_text": str, "files": list[str]}
    """
    import subprocess

    send_progress = context.get("send_progress", lambda x: None)
    combined = context["combined"]
    instruction = combined["combined_instruction"]
    task_dir = context.get("task_dir", "")

    send_progress("🖥️ 데스크톱 제어 작업을 준비합니다...")

    claude_exe = _find_claude_cli()
    if not claude_exe:
        return {
            "result_text": (
                "Claude CLI를 찾을 수 없습니다.\n\n"
                "설치: npm install -g @anthropic-ai/claude-code"
            ),
            "files": [],
        }

    # 시스템 프롬프트 파일
    project_root = Path(__file__).resolve().parent.parent.parent
    spf = project_root / "scripts" / "CLAUDE_TELEGRAM.md"
    if not spf.exists():
        spf = project_root / "CLAUDE.md"

    # 데스크톱 전용 프롬프트 — MCP 도구 안내 + 안전 규칙
    prompt = (
        f"DESKTOP CONTROL TASK via Telegram.\n\n"
        f"User instruction:\n{instruction}\n\n"
        f"Working directory for output files: {task_dir}\n\n"
        f"=== AVAILABLE MCP TOOLS FOR DESKTOP CONTROL ===\n"
        f"You have these MCP tools connected RIGHT NOW:\n\n"
        f"**Windows Controller MCP:**\n"
        f"- mcp__windows-controller__State-Tool: Capture desktop state "
        f"(apps, elements, coordinates). Set use_vision=True for screenshot.\n"
        f"- mcp__windows-controller__Click-Tool: Click at [x,y] coordinates\n"
        f"- mcp__windows-controller__Type-Tool: Type text at [x,y]\n"
        f"- mcp__windows-controller__Scroll-Tool: Scroll at coordinates\n"
        f"- mcp__windows-controller__Shortcut-Tool: Keyboard shortcuts "
        f"(e.g., 'alt+tab', 'win+r')\n"
        f"- mcp__windows-controller__App-Tool: Launch/resize apps by name "
        f"(NOTE: mode='switch' is BROKEN, use Powershell-Tool with AppActivate instead)\n"
        f"- mcp__windows-controller__Powershell-Tool: Execute PowerShell commands\n"
        f"- mcp__windows-controller__Scrape-Tool: Extract text from browser tab\n"
        f"- mcp__windows-controller__Move-Tool: Move mouse cursor\n"
        f"- mcp__windows-controller__Drag-Tool: Drag and drop\n"
        f"- mcp__windows-controller__Wait-Tool: Wait for loading\n\n"
        f"**Chrome MCP (for browser content):**\n"
        f"- mcp__Claude_in_Chrome__read_page: Get accessibility tree of page\n"
        f"- mcp__Claude_in_Chrome__find: Find elements by natural language\n"
        f"- mcp__Claude_in_Chrome__navigate: Navigate to URL\n"
        f"- mcp__Claude_in_Chrome__get_page_text: Extract page text\n"
        f"- mcp__Claude_in_Chrome__computer: Mouse/keyboard + screenshots\n\n"
        f"=== INSTRUCTIONS ===\n"
        f"1. Use State-Tool with use_vision=True FIRST to see the screen\n"
        f"2. For screenshots, save image to: {task_dir}\n"
        f"   Use Powershell-Tool:\n"
        f"   Add-Type -AssemblyName System.Windows.Forms\n"
        f"   $b=New-Object Drawing.Bitmap("
        f"[Windows.Forms.Screen]::PrimaryScreen.Bounds.Width,"
        f"[Windows.Forms.Screen]::PrimaryScreen.Bounds.Height)\n"
        f"   [Drawing.Graphics]::FromImage($b).CopyFromScreen(0,0,0,0,$b.Size)\n"
        f"   $b.Save('{task_dir}\\screenshot.png')\n"
        f"3. For listing programs: use Powershell-Tool with "
        f"Get-Process | Where MainWindowTitle | Format-Table Name,MainWindowTitle\n"
        f"4. For app control: State-Tool for coords, then Click/Type tools\n"
        f"5. For launching apps: App-Tool with mode='launch'\n"
        f"6. For browser content: use Chrome MCP tools\n"
        f"7. Save ALL output files to: {task_dir}\n\n"
        f"=== SAFETY RULES ===\n"
        f"- NEVER delete files, format disks, or empty trash\n"
        f"- NEVER access password managers or credential stores\n"
        f"- NEVER modify system registry or security settings\n"
        f"- NEVER install or uninstall software\n"
        f"- If dangerous action requested, politely refuse in Korean\n\n"
        f"=== RESPONSE FORMAT ===\n"
        f"- Report results concisely in Korean\n"
        f"- If screenshot taken, mention the file path\n"
        f"- List any files you created in {task_dir}\n"
    )

    cmd = [str(claude_exe), "-p", "--dangerously-skip-permissions"]
    if spf.exists():
        cmd.extend(["--append-system-prompt-file", str(spf)])

    try:
        send_progress("🖥️ Claude Code로 데스크톱 제어 실행 중...")

        result = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=600,
            cwd=(
                str(task_dir)
                if task_dir and Path(task_dir).is_dir()
                else str(project_root)
            ),
            encoding="utf-8",
        )

        output = result.stdout.strip()
        if result.returncode != 0 and not output:
            output = f"Claude CLI 실행 오류 (exit code {result.returncode})"
            if result.stderr:
                output += f"\n{result.stderr[:500]}"

        if not output:
            output = "작업이 완료되었으나 출력이 없습니다."

        # task_dir 내 생성된 파일 수집
        generated_files = []
        if task_dir and os.path.isdir(task_dir):
            for fname in os.listdir(task_dir):
                fpath = os.path.join(task_dir, fname)
                if os.path.isfile(fpath) and fname != "task_info.txt":
                    generated_files.append(fpath)

        return {
            "result_text": output[:4000],
            "files": generated_files,
        }

    except subprocess.TimeoutExpired:
        return {
            "result_text": "🖥️ 데스크톱 제어 시간 초과 (10분).",
            "files": [],
        }
    except Exception as e:
        return {
            "result_text": f"❌ 데스크톱 제어 오류: {e}\n{traceback.format_exc()[-500:]}",
            "files": [],
        }


def _reference_executor(context: dict) -> dict:
    """
    Reference 분류 메시지 → 메모리에 저장 + 간단 확인 응답.
    """
    combined = context.get("combined", {})
    instruction = combined.get("combined_instruction", "")
    snippet = instruction[:200] if instruction else "(내용 없음)"

    return {
        "result_text": (
            f"📌 참고 정보로 저장했습니다.\n\n"
            f"{snippet}\n\n"
            f"필요할 때 `메모리 조회`로 다시 확인할 수 있습니다."
        ),
        "files": [],
    }


def _decision_executor(context: dict) -> dict:
    """
    Decision 분류 메시지 → 판단/선택지 분석 후 응답.
    Claude CLI가 있으면 위임, 없으면 기본 응답.
    """
    # Claude CLI가 있으면 자연어 분석 위임 (더 스마트한 답변)
    if _find_claude_cli() is not None:
        return _run_claude_cli(context)

    combined = context.get("combined", {})
    instruction = combined.get("combined_instruction", "")[:200]

    return {
        "result_text": (
            f"🤔 질문을 확인했습니다.\n\n"
            f"\"{instruction}\"\n\n"
            f"Claude CLI가 설치되지 않아 자동 분석이 어렵습니다.\n"
            f"구체적인 명령어로 다시 보내주세요.\n"
            f"예: `브리핑 생성`, `이슈 동기화`, `전체점검`"
        ),
        "files": [],
    }


def _default_executor(context: dict) -> dict:
    """
    미매칭 명령 → 스킬 도움말 + 기존 명령 안내 메시지 반환.
    """
    combined = context.get("combined", {})
    instruction = combined.get("combined_instruction", "")[:100]

    # 스킬 도움말 시도
    try:
        from scripts.telegram.skills_registry import get_skill_help_text
        skill_help = get_skill_help_text()
    except Exception:
        skill_help = ""

    base_msg = (
        f"🤖 명령을 인식하지 못했습니다.\n\n"
        f"수신: \"{instruction}...\"\n\n"
    )

    if skill_help:
        return {
            "result_text": base_msg + skill_help + (
                f"\n\n**시스템 명령어:**\n"
                f"• `브리핑` — 일일 브리핑 생성\n"
                f"• `트리아지` — 이메일 분류\n"
                f"• `동기화` — 이슈 동기화\n"
                f"• `보고서` — 주간 보고서\n"
                f"• `아침루틴` — 아침 루틴\n"
                f"• `전체점검` — 전체 점검\n"
                f"• `마감점검` — 마감 점검\n"
            ),
            "files": [],
        }

    return {
        "result_text": base_msg + (
            f"**지원하는 명령어:**\n"
            f"• `브리핑` / `briefing` — 일일 브리핑 생성\n"
            f"• `트리아지` / `triage` — 이메일 분류\n"
            f"• `스캔` / `ocr` — OCR 처리\n"
            f"• `동기화` / `sync` — 이슈 동기화\n"
            f"• `보고서` / `report` — 주간 보고서\n"
            f"• `현황` / `metric` — 메트릭 현황\n"
            f"• `도움말` / `help` — 전체 스킬 목록\n"
            f"\n**복합 명령어:**\n"
            f"• `아침루틴` / `morning` — 아침 브리핑+메트릭\n"
            f"• `전체점검` — 전체 시스템 점검\n"
            f"• `마감점검` / `마감` — 마감 트리아지+동기화+큐\n"
        ),
        "files": [],
    }


# ── 신규 스킬 모듈 임포트 (lazy-import 패턴) ──────────────────

def _lazy_skill(module_path: str, func_name: str):
    """스킬 모듈에서 함수를 동적으로 로딩하는 래퍼 생성."""
    def _wrapper(context: dict) -> dict:
        import importlib
        try:
            mod = importlib.import_module(module_path)
            fn = getattr(mod, func_name)
            return fn(context)
        except Exception as exc:
            # 에러 분류 통합
            from scripts.telegram.error_handler import classify_error, handle_error
            severity, category = classify_error(exc)
            handle_error(exc, severity, category, context={
                "skill": func_name,
                "module": module_path,
            })
            return {
                "result_text": f"❌ 스킬 실행 오류 ({func_name}): {exc}\n{traceback.format_exc()[-500:]}",
                "files": [],
            }
    _wrapper.__name__ = func_name
    _wrapper.__doc__ = f"Lazy wrapper for {module_path}.{func_name}"
    return _wrapper

# 스킬 executor 래퍼 생성
_skill_help = _lazy_skill("scripts.telegram.skills.utility_skills", "run_skill_help")
_skill_issue_lookup = _lazy_skill("scripts.telegram.skills.utility_skills", "run_issue_lookup")
_skill_file_convert = _lazy_skill("scripts.telegram.skills.utility_skills", "run_file_convert")
_skill_quick_calc = _lazy_skill("scripts.telegram.skills.utility_skills", "run_quick_calc")
_skill_pdf_analyze = _lazy_skill("scripts.telegram.skills.analysis_skills", "run_pdf_analyze")
_skill_drawing_analyze = _lazy_skill("scripts.telegram.skills.analysis_skills", "run_drawing_analyze")
_skill_excel_analyze = _lazy_skill("scripts.telegram.skills.analysis_skills", "run_excel_analyze")
_skill_excel_report = _lazy_skill("scripts.telegram.skills.generation_skills", "run_excel_report")
_skill_ppt_generate = _lazy_skill("scripts.telegram.skills.generation_skills", "run_ppt_generate")
_skill_pdf_summary = _lazy_skill("scripts.telegram.skills.generation_skills", "run_pdf_summary")
_skill_email_response = _lazy_skill("scripts.telegram.skills.intelligence_skills", "run_email_response")
_skill_fabrication_status = _lazy_skill("scripts.telegram.skills.intelligence_skills", "run_fabrication_status")
_skill_meeting_prep = _lazy_skill("scripts.telegram.skills.intelligence_skills", "run_meeting_prep")

# Google 연동 스킬 executor 래퍼
_skill_gdrive_browse = _lazy_skill("scripts.telegram.skills.google_skills", "run_gdrive_browse")
_skill_gdrive_download = _lazy_skill("scripts.telegram.skills.google_skills", "run_gdrive_download")
_skill_email_check = _lazy_skill("scripts.telegram.skills.google_skills", "run_email_check")
_skill_gsheet_edit = _lazy_skill("scripts.telegram.skills.google_skills", "run_gsheet_edit")
_skill_gdoc_read = _lazy_skill("scripts.telegram.skills.google_skills", "run_gdoc_read")

# ── 이메일 강화 스킬 (lazy) ──
_skill_email_attachment = _lazy_skill("scripts.telegram.skills.email_skills", "run_email_attachment")
_skill_email_send = _lazy_skill("scripts.telegram.skills.email_skills", "run_email_send")
_skill_email_reply = _lazy_skill("scripts.telegram.skills.email_skills", "run_email_reply")

# ── 카카오톡 스킬 (lazy) ──
_skill_kakao_chat = _lazy_skill("scripts.telegram.skills.kakao_skills", "run_kakao_chat")
_skill_kakao_search = _lazy_skill("scripts.telegram.skills.kakao_skills", "run_kakao_search")
_skill_kakao_summary = _lazy_skill("scripts.telegram.skills.kakao_skills", "run_kakao_summary")

# ── 카카오톡 라이브 스킬 (MCP 기반, lazy) ──
_skill_kakao_live_read = _lazy_skill("scripts.telegram.skills.kakao_live_skills", "run_kakao_live_read")
_skill_kakao_room_list = _lazy_skill("scripts.telegram.skills.kakao_live_skills", "run_kakao_room_list")
_skill_kakao_reply_draft = _lazy_skill("scripts.telegram.skills.kakao_live_skills", "run_kakao_reply_draft")
_skill_kakao_send_confirm = _lazy_skill("scripts.telegram.skills.kakao_live_skills", "run_kakao_send_confirm")
_skill_kakao_send_cancel = _lazy_skill("scripts.telegram.skills.kakao_live_skills", "run_kakao_send_cancel")
_skill_kakao_context = _lazy_skill("scripts.telegram.skills.kakao_live_skills", "run_kakao_context")

# ── 구조 엔지니어링 스킬 (lazy) ──
_skill_cascade_analyzer = _lazy_skill("scripts.telegram.skills.engineering_skills", "run_cascade_analyzer")
_skill_stale_hunter = _lazy_skill("scripts.telegram.skills.engineering_skills", "run_stale_hunter")
_skill_decision_logger = _lazy_skill("scripts.telegram.skills.engineering_skills", "run_decision_logger")
_skill_lead_time_tracker = _lazy_skill("scripts.telegram.skills.engineering_skills", "run_lead_time_tracker")
_skill_contractor_digest = _lazy_skill("scripts.telegram.skills.engineering_skills", "run_contractor_digest")
_skill_weekly_executive = _lazy_skill("scripts.telegram.skills.engineering_skills", "run_weekly_executive")
_skill_spec_checker = _lazy_skill("scripts.telegram.skills.engineering_skills", "run_spec_checker")

# ── 물량 분석 스킬 (lazy) ──
_skill_quantity_analysis = _lazy_skill("scripts.telegram.skills.quantity_skills", "run_quantity_analysis")

# ── 자동화 5대 스킬 (lazy) ──
_skill_resend_failed = _lazy_skill("scripts.telegram.skills.system_skills", "run_resend_failed")
_skill_health_report = _lazy_skill("scripts.telegram.skills.system_skills", "run_health_report")
_skill_issue_trend = _lazy_skill("scripts.telegram.skills.dashboard_skills", "run_issue_trend")
_skill_kakao_daily_summary = _lazy_skill("scripts.telegram.skills.kakao_summary_skills", "run_kakao_daily_summary")
_skill_quantity_monitor = _lazy_skill("scripts.telegram.skills.quantity_monitor_skills", "run_quantity_monitor")
_skill_traceability_map = _lazy_skill("scripts.telegram.skills.traceability_skills", "run_traceability_map")

# ── 데스크톱 제어 스킬 executor (pywinauto 직접 실행) ──
_skill_desktop_control = _lazy_skill("scripts.telegram.skills.desktop_skills", "run_desktop_control")

# ── 회의록 이슈 연동 스킬 (lazy) ──
_skill_meeting_transcript = _lazy_skill("scripts.telegram.skills.meeting_skills", "run_meeting_transcript")
_skill_meeting_issue_approval = _lazy_skill("scripts.telegram.skills.meeting_skills", "run_meeting_issue_approval")


# Executor 레지스트리
EXECUTOR_MAP: Dict[str, Callable[[dict], dict]] = {
    # ── 기존 executor ──
    "daily_briefing": _run_briefing,
    "email_triage": _run_triage,
    "ocr_pipeline": _run_ocr,
    "issue_sync": _run_sync,
    "weekly_report": _run_report,
    "metrics": _run_metrics,
    # 복합 명령
    "morning_routine": _run_morning_routine,
    "full_check": _run_full_check,
    "closing_check": _run_closing_check,
    # 분류 기반 executor
    "reference": _reference_executor,
    "decision": _decision_executor,
    # ── 신규 스킬 executor ──
    "skill_help": _skill_help,
    "issue_lookup": _skill_issue_lookup,
    "file_convert": _skill_file_convert,
    "quick_calc": _skill_quick_calc,
    "pdf_analyze": _skill_pdf_analyze,
    "drawing_analyze": _skill_drawing_analyze,
    "excel_analyze": _skill_excel_analyze,
    "excel_report": _skill_excel_report,
    "ppt_generate": _skill_ppt_generate,
    "pdf_summary": _skill_pdf_summary,
    "email_response": _skill_email_response,
    "fabrication_status": _skill_fabrication_status,
    "meeting_prep": _skill_meeting_prep,
    # ── Google 연동 스킬 executor ──
    "gdrive_browse": _skill_gdrive_browse,
    "gdrive_download": _skill_gdrive_download,
    "email_check": _skill_email_check,
    "gsheet_edit": _skill_gsheet_edit,
    "gdoc_read": _skill_gdoc_read,
    # ── 이메일 강화 스킬 executor ──
    "email_attachment": _skill_email_attachment,
    "email_send": _skill_email_send,
    "email_reply": _skill_email_reply,
    # ── 카카오톡 스킬 executor (export 기반) ──
    "kakao_chat": _skill_kakao_chat,
    "kakao_search": _skill_kakao_search,
    "kakao_summary": _skill_kakao_summary,
    # ── 카카오톡 라이브 executor (MCP 기반) ──
    "kakao_live_read": _skill_kakao_live_read,
    "kakao_room_list": _skill_kakao_room_list,
    "kakao_reply_draft": _skill_kakao_reply_draft,
    "kakao_send_confirm": _skill_kakao_send_confirm,
    "kakao_send_cancel": _skill_kakao_send_cancel,
    "kakao_context": _skill_kakao_context,
    # ── 구조 엔지니어링 스킬 executor ──
    "cascade_analyzer": _skill_cascade_analyzer,
    "stale_hunter": _skill_stale_hunter,
    "decision_logger": _skill_decision_logger,
    "lead_time_tracker": _skill_lead_time_tracker,
    "contractor_digest": _skill_contractor_digest,
    "weekly_executive": _skill_weekly_executive,
    "spec_checker": _skill_spec_checker,
    # ── 물량 분석 스킬 executor ──
    "quantity_analysis": _skill_quantity_analysis,
    # ── 자동화 5대 스킬 executor ──
    "resend_failed": _skill_resend_failed,
    "health_report": _skill_health_report,
    "issue_trend": _skill_issue_trend,
    "kakao_daily_summary": _skill_kakao_daily_summary,
    "quantity_monitor": _skill_quantity_monitor,
    "traceability_map": _skill_traceability_map,
    # ── 데스크톱 원격 제어 executor (pywinauto 직접 실행) ──
    "desktop_control": _skill_desktop_control,
    # ── 회의록 이슈 연동 executor ──
    "meeting_transcript": _skill_meeting_transcript,
    "meeting_issue_approval": _skill_meeting_issue_approval,
}


# ── 복잡한 작업 요청 감지 (Complexity Guard) ─────────────────

# 항상 매칭 허용하는 명시적 명령 키워드 (guard 우회)
_ALWAYS_MATCH_KEYWORDS = frozenset({
    # 카카오톡 라이브 (구체적 명령)
    "카톡읽기", "카톡실시간", "카톡라이브", "카톡방목록", "카톡방리스트",
    "열린카톡", "카톡보내", "카톡전송", "카톡입력", "카톡맥락", "카톡상황",
    "카톡답변",
    # 도움말 (명시적)
    "도움말", "help", "명령어",
    # 데스크톱 캡처 (구체적)
    "화면캡처", "스크린샷", "screenshot", "지금화면",
    # 복합 루틴 (명시적)
    "아침루틴", "전체점검", "마감점검",
    # 자동화 5대 스킬 (명시적)
    "재전송", "전송실패", "헬스체크", "시스템점검", "이슈트렌드",
    "물량감시", "물량변동", "연계추적", "카톡요약리포트",
    # 회의록 이슈 연동 (명시적)
    "회의록정리", "회의록분석", "회의내용정리", "미팅노트", "미팅정리",
    "통화내용정리", "통화정리", "회의이슈연동", "회의결과정리",
    "회의이슈", "회의록", "회의내용", "통화내용",
    "이슈생성승인", "이슈승인",
})

# 짧은 키워드 오매칭 방지 임계값
_SHORT_KEYWORD_MAX_LEN = 3  # 3자 이하 키워드는 복합어 검사
_COMPLEX_MSG_MIN_LEN = 30   # 30자 이상이면 복잡한 메시지 후보
_COMPLEX_MSG_MIN_WORDS = 5  # 5단어 이상이면 복잡한 메시지 후보

# 한국어 작업 동사 어미 (복잡한 작업 지시를 나타내는 패턴)
_WORK_VERB_SUFFIXES = (
    "해줘", "해주세요", "해봐", "해라", "해주라",
    "만들어", "만들어줘", "만들어주세요",
    "구축해줘", "구축해주세요",
    "정리해줘", "정리해주세요",
    "분석해줘", "분석해주세요",
    "검토해줘", "검토해주세요",
    "작성해줘", "작성해주세요",
    "처리해줘", "처리해주세요",
    "준비해줘", "준비해주세요",
    "알려줘", "알려주세요",
    "설명해줘", "설명해주세요",
    "조사해줘", "조사해주세요",
    "보내줘", "보내주세요",
)


def _is_complex_work_request(text: str, matched_keyword: str) -> bool:
    """메시지가 단순 키워드 명령이 아닌 복잡한 작업 요청인지 판별.

    단순 명령("스킬 목록", "메일확인")은 False를 반환하여 키워드 매칭 허용.
    복잡한 작업 지시("...스킬구축해줘")는 True를 반환하여 Claude Code로 넘김.

    Args:
        text: 원본 메시지 텍스트
        matched_keyword: KEYWORD_MAP에서 매칭된 키워드

    Returns:
        True: 복잡한 작업 → 키워드 매칭 건너뛰기
        False: 단순 명령 → 키워드 매칭 허용
    """
    # 항상 매칭 키워드는 guard 우회
    if matched_keyword in _ALWAYS_MATCH_KEYWORDS:
        return False

    text_stripped = text.strip()
    text_len = len(text_stripped)
    words = text_stripped.split()
    word_count = len(words)

    # 짧은 메시지 AND 적은 단어 수 → 단순 명령
    if text_len < _COMPLEX_MSG_MIN_LEN and word_count < _COMPLEX_MSG_MIN_WORDS:
        return False

    # 짧은 키워드(≤3자)의 복합어 검사
    if len(matched_keyword) <= _SHORT_KEYWORD_MAX_LEN:
        text_nospace = text_stripped.lower().replace(" ", "")
        kw_lower = matched_keyword.lower()
        idx = text_nospace.find(kw_lower)
        if idx >= 0:
            after_idx = idx + len(kw_lower)
            if after_idx < len(text_nospace):
                after_char = text_nospace[after_idx]
                # 키워드 뒤에 한글이 바로 붙어있으면 복합어
                if "\uac00" <= after_char <= "\ud7a3":
                    return True

    # 긴 메시지 + 작업 동사 어미 → 복잡한 작업
    if text_len > 50 or word_count > 6:
        if any(text_stripped.rstrip().endswith(suffix) for suffix in _WORK_VERB_SUFFIXES):
            return True

    return False


# ── Stability Gate ──────────────────────────────────────────

# 캐시: executor_name → stability (lazy 로드)
_SKILL_STABILITY_CACHE: Optional[Dict[str, str]] = None


def _load_skill_stability() -> Dict[str, str]:
    """skills_registry에서 executor_name → stability 매핑 구축."""
    global _SKILL_STABILITY_CACHE
    if _SKILL_STABILITY_CACHE is not None:
        return _SKILL_STABILITY_CACHE
    try:
        from scripts.telegram.skills_registry import SKILLS
        # skill_id는 EXECUTOR_MAP의 키와 동일
        _SKILL_STABILITY_CACHE = {
            s.skill_id: s.stability for s in SKILLS.values()
        }
    except Exception:
        _SKILL_STABILITY_CACHE = {}
    return _SKILL_STABILITY_CACHE


def _is_experimental_skill(executor_name: str, instruction_text: str) -> bool:
    """experimental 스킬인데 '실험'/'experimental' 접두사가 없으면 True.

    experimental 스킬이 아니거나 접두사가 있으면 False (매칭 허용).
    """
    stability_map = _load_skill_stability()
    stability = stability_map.get(executor_name, "stable")
    if stability != "experimental":
        return False
    # 접두사 확인
    text_lower = instruction_text.lower().strip()
    if text_lower.startswith("실험") or text_lower.startswith("experimental"):
        return False
    return True


def _detect_google_url(text: str) -> Optional[str]:
    """텍스트에서 Google URL을 감지하여 적절한 executor 이름 반환.

    Returns:
        매칭된 executor 이름 또는 None
    """
    import re
    # Google URL 패턴 → executor 매핑
    _GOOGLE_URL_ROUTES = [
        (r"docs\.google\.com/spreadsheets/d/", "gsheet_edit"),
        (r"docs\.google\.com/document/d/", "gdoc_read"),
        (r"drive\.google\.com/drive/(?:u/\d+/)?folders/", "gdrive_browse"),
        (r"drive\.google\.com/file/d/", "gdrive_download"),
        (r"drive\.google\.com/open\?id=", "gdrive_download"),
    ]
    for pattern, executor_name in _GOOGLE_URL_ROUTES:
        if re.search(pattern, text):
            return executor_name
    return None


def get_executor(
    instruction_text: str,
    classification: str = "action",
    files: Optional[List[Dict]] = None,
) -> Callable[[dict], dict]:
    """
    메시지 분류 + Google URL 감지 + 키워드 매칭 + 파일 자동감지로 적절한 executor 반환.

    Args:
        instruction_text: 텔레그램에서 수신한 지시 텍스트
        classification: 메시지 분류 ("action", "decision", "reference", "trash")
        files: 첨부 파일 정보 리스트 (optional)

    Returns:
        executor 함수 (context → {"result_text": str, "files": list})
    """
    # 분류별 라우팅 — action이 아닌 경우 전용 executor 우선
    if classification == "reference":
        return _reference_executor
    if classification == "decision":
        # decision_logger 키워드 우선 확인
        dl_keywords = ["결정기록", "결정사항", "의사결정", "회의결정", "결정등록"]
        text_lower_check = instruction_text.lower()
        if any(kw in text_lower_check for kw in dl_keywords):
            return EXECUTOR_MAP.get("decision_logger", _decision_executor)
        # SEN-ID + "결정" 패턴도 decision_logger로 라우팅
        import re as _re
        if _re.search(r"SEN-\d+.*결정", instruction_text, _re.IGNORECASE):
            return EXECUTOR_MAP.get("decision_logger", _decision_executor)
        return _decision_executor

    # Google URL 자동 라우팅 (키워드 매칭보다 우선)
    google_executor_name = _detect_google_url(instruction_text)
    if google_executor_name:
        executor = EXECUTOR_MAP.get(google_executor_name)
        if executor:
            return executor

    # 카카오톡 답장 대기 확인 (키워드 매칭보다 우선)
    _pending_reply_file = Path(__file__).resolve().parent.parent.parent / "telegram_data" / "kakao_pending_reply.json"
    if _pending_reply_file.exists():
        text_lower_tmp = instruction_text.lower().strip()
        _confirm_kw = ["보내", "전송", "send", "확인", "ok", "ㅇㅋ"]
        _cancel_kw = ["취소", "cancel", "그만", "중지", "삭제"]
        if any(kw in text_lower_tmp for kw in _confirm_kw):
            executor = EXECUTOR_MAP.get("kakao_send_confirm")
            if executor:
                return executor
        if any(kw in text_lower_tmp for kw in _cancel_kw):
            executor = EXECUTOR_MAP.get("kakao_send_cancel")
            if executor:
                return executor

    # Action (기본): 키워드 매칭으로 executor 선택
    text_lower = instruction_text.lower()
    # 공백 제거 버전도 준비 (한국어 띄어쓰기 변형 대응: "화면 보여줘" → "화면보여줘")
    text_nospace = text_lower.replace(" ", "")
    for keyword, executor_name in KEYWORD_MAP.items():
        if keyword in text_lower or keyword in text_nospace:
            # Complexity Guard: 복잡한 작업 요청이면 키워드 매칭 건너뛰기
            if _is_complex_work_request(instruction_text, keyword):
                print(f"[COMPLEXITY_GUARD] Skipped keyword '{keyword}' "
                      f"→ complex work request (len={len(instruction_text)})")
                continue
            # Stability Gate: experimental 스킬은 "실험" 접두사 필요
            # (_ALWAYS_MATCH_KEYWORDS는 stability gate도 우회)
            if keyword not in _ALWAYS_MATCH_KEYWORDS and _is_experimental_skill(executor_name, instruction_text):
                print(f"[STABILITY_GATE] Skipped experimental skill '{executor_name}' "
                      f"→ missing '실험'/'experimental' prefix")
                continue
            executor = EXECUTOR_MAP.get(executor_name)
            if executor:
                return executor

    # 파일 자동 라우팅: 키워드 미매칭이지만 파일이 첨부된 경우
    if files:
        file_executor = _route_by_file_type(files, text_lower)
        if file_executor:
            return file_executor

    # 키워드 미매칭 → Claude CLI 설치 시 위임, 아니면 안내 메시지
    if _find_claude_cli() is not None:
        return _run_claude_cli
    return _default_executor


# MCP 의존 executor 집합 — Python 직행 불가, Claude Code 세션 필요
# 카카오톡 스킬 6종 + 데스크톱 제어 모두 pywinauto 직접 제어로 전환됨
# → 모든 스킬이 Step 2(python_runner)에서 직행 실행 가능 (LLM 토큰 0)
_MCP_DEPENDENT_EXECUTORS = frozenset()


def is_direct_skill(
    instruction_text: str,
    classification: str = "action",
    files: Optional[List[Dict]] = None,
) -> bool:
    """키워드 매칭으로 직행 실행 가능한지 판별.

    get_executor()로 결정된 executor가 순수 Python 스킬이면 True.
    _run_claude_cli, _default_executor, 또는 MCP 의존 executor이면 False.

    모든 스킬은 pywinauto 직접 제어로 전환되어 MCP 의존성이 없으므로
    Python subprocess에서 직행 실행 가능하다.

    Args:
        instruction_text: 텔레그램에서 수신한 지시 텍스트
        classification: 메시지 분류
        files: 첨부 파일 정보 리스트

    Returns:
        True: Python 직행 실행 가능
        False: Claude Code 필요
    """
    executor = get_executor(instruction_text, classification, files)

    # Claude CLI 위임 또는 기본 executor → 직행 불가
    if executor in (_run_claude_cli, _default_executor):
        executor_name = getattr(executor, "__name__", str(executor))
        print(f"[EXECUTOR_ROUTING] Not direct skill → {executor_name} "
              f"(instruction: {instruction_text[:80]}...)")
        return False

    # MCP 의존 executor → Python 직행 불가, Claude Code 세션 필요
    if executor in _MCP_DEPENDENT_EXECUTORS:
        executor_name = getattr(executor, "__name__", str(executor))
        print(f"[EXECUTOR_ROUTING] MCP-dependent skill → {executor_name} "
              f"(requires Claude Code session with MCP tools)")
        return False

    return True


def _route_by_file_type(
    files: List[Dict], text_lower: str
) -> Optional[Callable[[dict], dict]]:
    """
    첨부 파일 확장자 기반으로 적절한 스킬 executor 자동 선택.

    Returns:
        매칭된 executor 또는 None
    """
    _DRAWING_KEYWORDS = [
        "도면", "drawing", "shop", "드로잉", "구조", "structural",
        "blueprint", "치수", "철근", "단면", "배근", "상세도",
    ]

    for f in files:
        name = f.get("name", "")
        _, ext = os.path.splitext(name)
        ext_lower = ext.lower()

        # 음성/오디오 + 회의 키워드 → 회의록 이슈 연동
        if ext_lower in (".ogg", ".opus", ".mp3", ".m4a", ".wav"):
            meeting_kw = ["회의", "미팅", "통화", "회의록", "meeting", "call"]
            if any(kw in text_lower for kw in meeting_kw):
                return EXECUTOR_MAP.get("meeting_transcript")

        # DXF/DWG → 항상 도면 분석
        if ext_lower in (".dxf", ".dwg"):
            return EXECUTOR_MAP.get("drawing_analyze")

        if ext_lower == ".pdf":
            # PDF + 도면 키워드 → 도면 분석
            if any(kw in text_lower for kw in _DRAWING_KEYWORDS):
                return EXECUTOR_MAP.get("drawing_analyze")
            # PDF 기본 → PDF 분석
            return EXECUTOR_MAP.get("pdf_analyze")

        if ext_lower in (".png", ".jpg", ".jpeg"):
            # 이미지 + 도면 키워드 → 도면 분석
            if any(kw in text_lower for kw in _DRAWING_KEYWORDS):
                return EXECUTOR_MAP.get("drawing_analyze")
            # 이미지 단독 → 도면 분석 아님 (OCR 등 다른 처리)
            continue

        if ext_lower in (".xlsx", ".xls", ".csv"):
            # Excel 기본 → 엑셀 분석
            return EXECUTOR_MAP.get("excel_analyze")

    return None


def list_executors() -> List[str]:
    """등록된 executor 이름 목록 반환."""
    return list(EXECUTOR_MAP.keys())
