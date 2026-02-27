#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
스킬 레지스트리 — 전체 스킬 메타데이터 관리

스킬 정의, 도움말 생성, 스킬 검색 등을 담당.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class SkillDef:
    """스킬 메타데이터 정의."""

    skill_id: str           # "pdf_analyze"
    name_ko: str            # "PDF 분석"
    category: str           # "analysis" | "generation" | "intelligence" | "utility"
    description_ko: str     # 한줄 설명
    keywords_ko: List[str]  # 한국어 트리거 키워드
    keywords_en: List[str]  # 영어 트리거 키워드
    requires_file: bool     # 파일 첨부 필수 여부
    file_types: List[str]   # 허용 확장자 (e.g., [".pdf"])
    output_type: str        # "text" | "file" | "both"
    examples_ko: List[str]  # 사용 예시
    phase: int = 1          # 구현 페이즈 (1, 2, 3)
    implemented: bool = True  # 구현 완료 여부
    stability: str = "stable"  # "stable" | "experimental" | "deprecated"


# ═══════════════════════════════════════════════════════════════
#  스킬 정의 (31개)
# ═══════════════════════════════════════════════════════════════

SKILLS: Dict[str, SkillDef] = {
    # ── Phase 1: 핵심 스킬 ──
    "skill_help": SkillDef(
        skill_id="skill_help",
        name_ko="도움말",
        category="utility",
        description_ko="사용 가능한 스킬 목록과 사용법 안내",
        keywords_ko=["도움말", "도움", "명령어", "스킬", "기능"],
        keywords_en=["help", "commands", "skills"],
        requires_file=False,
        file_types=[],
        output_type="text",
        examples_ko=["도움말", "뭘 할 수 있어?", "스킬 목록"],
        phase=1,
    ),
    "issue_lookup": SkillDef(
        skill_id="issue_lookup",
        name_ko="이슈 조회",
        category="utility",
        description_ko="P5 프로젝트 이슈를 ID 또는 키워드로 검색",
        keywords_ko=["이슈조회", "이슈검색", "조회"],
        keywords_en=["issue", "lookup", "search"],
        requires_file=False,
        file_types=[],
        output_type="text",
        examples_ko=["SEN-070 조회", "PSRC 이슈 검색", "이슈조회 구조접합"],
        phase=1,
    ),
    "pdf_analyze": SkillDef(
        skill_id="pdf_analyze",
        name_ko="PDF 분석",
        category="analysis",
        description_ko="PDF 문서 텍스트 추출 및 구조 분석",
        keywords_ko=["pdf분석", "문서분석", "도서분석", "pdf확인"],
        keywords_en=["pdf", "document analysis"],
        requires_file=True,
        file_types=[".pdf"],
        output_type="both",
        examples_ko=["이 PDF 분석해줘", "문서 내용 정리해줘"],
        phase=1,
    ),
    "email_response": SkillDef(
        skill_id="email_response",
        name_ko="이메일 답신 방향",
        category="intelligence",
        description_ko="수신 이메일에 대한 답신 전략 및 초안 제안",
        keywords_ko=["답신", "답장", "회신", "메일답변", "답변방향"],
        keywords_en=["reply", "response", "email draft"],
        requires_file=False,
        file_types=[],
        output_type="text",
        examples_ko=["이 메일 답신 방향 잡아줘", "회신 초안 만들어줘"],
        phase=1,
    ),
    "fabrication_status": SkillDef(
        skill_id="fabrication_status",
        name_ko="제작/납품 현황",
        category="intelligence",
        description_ko="부재별 제작 단계 및 납품 현황 매트릭스",
        keywords_ko=["제작현황", "납품현황", "부재현황", "제작상태"],
        keywords_en=["fab", "fabrication", "delivery"],
        requires_file=False,
        file_types=[],
        output_type="text",
        examples_ko=["제작현황 알려줘", "PSRC 납품현황", "부재 제작 상태"],
        phase=1,
    ),

    # ── Phase 2: 생성 + 분석 확장 ──
    "excel_report": SkillDef(
        skill_id="excel_report",
        name_ko="엑셀 보고서",
        category="generation",
        description_ko="이슈 현황 엑셀 보고서 자동 생성",
        keywords_ko=["엑셀보고서", "현황표", "이슈엑셀", "엑셀생성"],
        keywords_en=["excel report", "spreadsheet"],
        requires_file=False,
        file_types=[],
        output_type="file",
        examples_ko=["이슈현황 엑셀 만들어줘", "현황표 생성", "엑셀보고서"],
        phase=2,
    ),
    "excel_analyze": SkillDef(
        skill_id="excel_analyze",
        name_ko="엑셀 분석",
        category="analysis",
        description_ko="첨부된 엑셀/CSV 파일 데이터 요약 분석",
        keywords_ko=["엑셀분석", "데이터분석", "boq분석", "엑셀확인"],
        keywords_en=["excel", "data analysis", "boq"],
        requires_file=True,
        file_types=[".xlsx", ".xls", ".csv"],
        output_type="text",
        examples_ko=["이 엑셀 분석해줘", "BOQ 내용 정리해줘"],
        phase=2,
    ),
    "drawing_analyze": SkillDef(
        skill_id="drawing_analyze",
        name_ko="도면 정밀 분석",
        category="analysis",
        description_ko="건설 구조 도면 정밀 분석 (치수/구조상세/그리드/수량/품질평가)",
        keywords_ko=[
            "도면분석", "드로잉", "도면확인", "shop도면",
            "치수분석", "철근분석", "단면분석", "구조분석",
        ],
        keywords_en=["drawing", "dwg", "dxf", "blueprint", "structural"],
        requires_file=True,
        file_types=[".pdf", ".png", ".jpg", ".jpeg", ".dxf", ".dwg"],
        output_type="both",
        examples_ko=[
            "이 도면 분석해줘", "도면번호 추출해줘", "shop 도면 확인",
            "이 도면 치수 분석해줘", "구조 도면 상세 분석",
        ],
        phase=2,
    ),
    "meeting_prep": SkillDef(
        skill_id="meeting_prep",
        name_ko="회의 준비",
        category="intelligence",
        description_ko="회의 안건 및 사전 준비자료 자동 구성",
        keywords_ko=["회의준비", "회의자료", "아젠다", "회의안건"],
        keywords_en=["meeting", "agenda"],
        requires_file=False,
        file_types=[],
        output_type="text",
        examples_ko=["주간회의 준비해줘", "내일 회의 아젠다 만들어줘"],
        phase=2,
    ),
    "file_convert": SkillDef(
        skill_id="file_convert",
        name_ko="파일 변환",
        category="utility",
        description_ko="PDF↔이미지, Excel→PDF 등 파일 포맷 변환",
        keywords_ko=["변환", "컨버트", "파일변환"],
        keywords_en=["convert", "transform"],
        requires_file=True,
        file_types=[".pdf", ".xlsx", ".xls", ".png", ".jpg"],
        output_type="file",
        examples_ko=["PDF를 이미지로 변환해줘", "엑셀을 PDF로"],
        phase=2,
    ),

    # ── Phase 2: Google 연동 ──
    "gdrive_browse": SkillDef(
        skill_id="gdrive_browse",
        name_ko="Drive 파일 검색",
        category="google",
        description_ko="Google Drive 공유 폴더 파일 목록 및 검색",
        keywords_ko=["구글드라이브", "공유폴더", "드라이브검색", "드라이브목록"],
        keywords_en=["google drive", "drive browse", "shared folder"],
        requires_file=False,
        file_types=[],
        output_type="text",
        examples_ko=["구글드라이브 확인", "공유폴더 파일 목록", "드라이브에서 PSRC 검색"],
        phase=2,
    ),
    "gdrive_download": SkillDef(
        skill_id="gdrive_download",
        name_ko="Drive 다운로드",
        category="google",
        description_ko="Google Drive 파일 다운로드 후 텔레그램 전송",
        keywords_ko=["드라이브다운", "파일다운로드"],
        keywords_en=["drive download"],
        requires_file=False,
        file_types=[],
        output_type="file",
        examples_ko=["이 파일 다운로드해줘", "드라이브에서 다운받아"],
        phase=2,
    ),
    "email_check": SkillDef(
        skill_id="email_check",
        name_ko="이메일 확인",
        category="google",
        description_ko="최근 수신 이메일 조회 (Outlook/IMAP)",
        keywords_ko=["메일확인", "메일조회", "받은메일", "최근메일"],
        keywords_en=["check email", "inbox", "recent mail"],
        requires_file=False,
        file_types=[],
        output_type="text",
        examples_ko=["메일확인", "오늘 받은 메일", "최근메일 5개"],
        phase=2,
    ),
    "gsheet_edit": SkillDef(
        skill_id="gsheet_edit",
        name_ko="구글시트 편집",
        category="google",
        description_ko="Google Sheets 데이터 조회 및 셀 수정",
        keywords_ko=["구글시트", "시트조회", "시트수정", "스프레드시트"],
        keywords_en=["google sheets", "spreadsheet"],
        requires_file=False,
        file_types=[],
        output_type="text",
        examples_ko=["구글시트 조회", "B5셀에 '완료' 입력", "시트 현황 보여줘"],
        phase=2,
    ),
    "gdoc_read": SkillDef(
        skill_id="gdoc_read",
        name_ko="구글문서 읽기",
        category="google",
        description_ko="Google Docs 문서 텍스트 추출",
        keywords_ko=["구글문서", "문서읽기"],
        keywords_en=["google docs", "gdoc"],
        requires_file=False,
        file_types=[],
        output_type="both",
        examples_ko=["구글문서 읽어줘", "이 문서 내용 확인"],
        phase=2,
    ),

    # ── Phase 2: 이메일 강화 ──
    "email_attachment": SkillDef(
        skill_id="email_attachment",
        name_ko="첨부파일 분석",
        category="email",
        description_ko="이메일 첨부파일 다운로드 + 자동 분석 (PDF/Excel)",
        keywords_ko=["첨부파일분석", "첨부확인", "첨부다운", "메일첨부"],
        keywords_en=["attachment", "email attachment"],
        requires_file=False,
        file_types=[],
        output_type="both",
        examples_ko=["마지막 메일 첨부파일 분석", "첨부파일 확인", "메일 첨부 다운"],
        phase=2,
    ),
    "email_send": SkillDef(
        skill_id="email_send",
        name_ko="이메일 발송",
        category="email",
        description_ko="Outlook으로 새 이메일 작성 및 발송 (2단계 확인)",
        keywords_ko=["메일발송", "메일보내", "메일전송", "메일작성"],
        keywords_en=["send email", "compose email"],
        requires_file=False,
        file_types=[],
        output_type="text",
        examples_ko=["김과장한테 이슈현황 메일 보내줘", "메일발송 to:xxx 제목:회의록"],
        phase=2,
    ),
    "email_reply": SkillDef(
        skill_id="email_reply",
        name_ko="이메일 회신",
        category="email",
        description_ko="수신 메일에 답장 또는 전체답장 (2단계 확인)",
        keywords_ko=["메일회신", "메일답장", "전체회신"],
        keywords_en=["reply email", "reply all"],
        requires_file=False,
        file_types=[],
        output_type="text",
        examples_ko=["마지막 메일에 답장 - 확인했습니다", "SEN-070 메일 회신"],
        phase=2,
    ),

    # ── Phase 2: 카카오톡 연동 ──
    "kakao_chat": SkillDef(
        skill_id="kakao_chat",
        name_ko="카톡 조회",
        category="kakao",
        description_ko="카카오톡 P5 채팅방 목록 및 메시지 조회",
        keywords_ko=["카톡", "카카오", "카톡확인", "카톡목록"],
        keywords_en=["kakao", "kakaotalk"],
        requires_file=False,
        file_types=[],
        output_type="text",
        examples_ko=["카톡 목록", "카톡 P5 현장", "카톡 최근"],
        phase=2,
    ),
    "kakao_search": SkillDef(
        skill_id="kakao_search",
        name_ko="카톡 검색",
        category="kakao",
        description_ko="카카오톡 P5 채팅방 메시지 키워드 검색",
        keywords_ko=["카톡검색", "카카오검색"],
        keywords_en=["kakao search"],
        requires_file=False,
        file_types=[],
        output_type="text",
        examples_ko=["카톡검색 PSRC 납품", "카카오검색 SEN-070"],
        phase=2,
    ),
    "kakao_summary": SkillDef(
        skill_id="kakao_summary",
        name_ko="카톡 요약/답장",
        category="kakao",
        description_ko="P5 채팅방 업무 맥락 요약 및 답장 방향 제시",
        keywords_ko=["카톡요약", "카카오요약", "카톡답장", "카카오답장"],
        keywords_en=["kakao summary", "kakao reply"],
        requires_file=False,
        file_types=[],
        output_type="text",
        examples_ko=["카톡요약 P5 현장", "카톡답장 구조검토"],
        phase=2,
    ),

    # ── Phase 5: 카카오톡 라이브 (MCP 기반) ──
    "kakao_live_read": SkillDef(
        skill_id="kakao_live_read",
        name_ko="카톡 실시간 읽기",
        category="kakao_live",
        description_ko="카카오톡 PC 앱에서 실시간 대화 읽기 (클립보드 방식)",
        keywords_ko=["카톡읽기", "카톡실시간", "실시간카톡", "카톡라이브", "카톡지금"],
        keywords_en=["kakao live", "kakao read"],
        requires_file=False,
        file_types=[],
        output_type="text",
        examples_ko=["카톡읽기 P5현장", "카톡 실시간 확인", "실시간카톡 P5"],
        phase=5,
    ),
    "kakao_room_list": SkillDef(
        skill_id="kakao_room_list",
        name_ko="카톡 방 목록 (라이브)",
        category="kakao_live",
        description_ko="카카오톡 PC 앱에서 열린 채팅방 목록 실시간 조회",
        keywords_ko=["카톡방목록", "카톡방리스트", "열린카톡"],
        keywords_en=["kakao rooms", "kakao room list"],
        requires_file=False,
        file_types=[],
        output_type="text",
        examples_ko=["카톡방목록", "열린카톡", "카톡방리스트"],
        phase=5,
    ),
    "kakao_reply_draft": SkillDef(
        skill_id="kakao_reply_draft",
        name_ko="카톡 답장 초안",
        category="kakao_live",
        description_ko="카카오톡 입력창에 답장 초안 입력 (전송 전 확인 필요)",
        keywords_ko=["카톡보내", "카톡전송", "카톡입력"],
        keywords_en=["kakao send", "kakao reply"],
        requires_file=False,
        file_types=[],
        output_type="text",
        examples_ko=["카톡보내 P5현장 내일 회의 10시입니다", "카톡전송 P5 확인했습니다"],
        phase=5,
    ),
    "kakao_context": SkillDef(
        skill_id="kakao_context",
        name_ko="카톡 맥락 분석",
        category="kakao_live",
        description_ko="채팅방 대화 맥락 분석 + 액션 아이템 + 답변 방향 제시",
        keywords_ko=["카톡맥락", "카톡상황", "카톡답변", "카톡답변제안", "카톡뭐라고할까"],
        keywords_en=["kakao context", "kakao analysis"],
        requires_file=False,
        file_types=[],
        output_type="text",
        examples_ko=["카톡맥락 P5현장", "카톡상황 구조검토", "카톡뭐라고할까 P5"],
        phase=5,
    ),
    "kakao_send_confirm": SkillDef(
        skill_id="kakao_send_confirm",
        name_ko="카톡 전송 확인",
        category="kakao_live",
        description_ko="대기 중인 카톡 답장 전송 확인 (Enter 누름)",
        keywords_ko=["보내", "전송확인"],
        keywords_en=["send", "confirm"],
        requires_file=False,
        file_types=[],
        output_type="text",
        examples_ko=["보내", "전송", "확인"],
        phase=5,
    ),

    # ── Phase 6: 물량 분석 ──
    "quantity_analysis": SkillDef(
        skill_id="quantity_analysis",
        name_ko="골조 물량 분석",
        category="engineering",
        description_ko="P5 복합동 선제작(RISK 발주) 골조 물량 조회/분석/비교",
        keywords_ko=[
            "물량", "물량분석", "물량조회", "골조물량",
            "선제작", "리스크발주", "RISK발주",
            "물량비교", "물량증가", "물량변화",
        ],
        keywords_en=["quantity", "boq", "risk order"],
        requires_file=False,
        file_types=[],
        output_type="text",
        examples_ko=[
            "물량분석", "PSRC 물량 얼마나 증가해?",
            "선제작 리스크 발주 물량", "PC 물량 비교",
            "물량 변경점 정리", "CASE 1 vs CASE 2 비교",
        ],
        phase=6,
        stability="experimental",
    ),

    # ── Phase 7: 회의록 이슈 연동 ──
    "meeting_transcript": SkillDef(
        skill_id="meeting_transcript",
        name_ko="회의록 이슈 연동",
        category="intelligence",
        description_ko="회의/통화 내용을 분석하여 이슈 자동 연동 및 회의록 생성",
        keywords_ko=["회의록", "회의내용", "통화내용", "미팅정리", "회의결과"],
        keywords_en=["meeting transcript", "meeting minutes"],
        requires_file=False,
        file_types=[".ogg", ".mp3", ".m4a", ".wav", ".opus"],
        output_type="both",
        examples_ko=["회의록정리 구조검토회의 SEN-428 논의...", "(음성메시지 + 회의록)"],
        phase=7,
        stability="experimental",
    ),
    "meeting_issue_approval": SkillDef(
        skill_id="meeting_issue_approval",
        name_ko="회의 이슈 생성 승인",
        category="utility",
        description_ko="회의에서 제안된 새 이슈를 승인하여 생성",
        keywords_ko=["이슈승인", "이슈생성승인"],
        keywords_en=["approve issue"],
        requires_file=False,
        file_types=[],
        output_type="text",
        examples_ko=["이슈승인 1번", "이슈승인"],
        phase=7,
        stability="experimental",
    ),

    # ── Phase 3: 고급 스킬 (stub) ──
    "ppt_generate": SkillDef(
        skill_id="ppt_generate",
        name_ko="발표자료 생성",
        category="generation",
        description_ko="주간회의용 PPT 발표자료 자동 생성",
        keywords_ko=["발표자료", "ppt", "프레젠테이션", "슬라이드"],
        keywords_en=["ppt", "presentation", "slides"],
        requires_file=False,
        file_types=[],
        output_type="file",
        examples_ko=["주간회의 발표자료 만들어줘", "PPT 생성"],
        phase=3,
        implemented=False,
    ),
    # ── Phase 4A: 구조 엔지니어링 스킬 ──
    "cascade_analyzer": SkillDef(
        skill_id="cascade_analyzer",
        name_ko="이슈 연쇄 분석",
        category="engineering",
        description_ko="SEN 이슈 간 종속관계 그래프 + 파급효과 점수 + 조치 우선순위",
        keywords_ko=["연쇄분석", "파급분석", "파급효과", "연관분석", "영향분석", "종속관계"],
        keywords_en=["cascade", "impact analysis", "dependency"],
        requires_file=False,
        file_types=[],
        output_type="text",
        examples_ko=["SEN-428 연쇄분석", "PSRC 파급효과", "영향분석 임베디드"],
        phase=4,
        stability="experimental",
    ),
    "stale_hunter": SkillDef(
        skill_id="stale_hunter",
        name_ko="방치 이슈 탐지",
        category="engineering",
        description_ko="방치/미결/무주 이슈 자동 탐지 + 에스컬레이션 제안",
        keywords_ko=["방치이슈", "장기미결", "미결이슈", "방치탐지", "지연이슈", "에스컬레이션"],
        keywords_en=["stale", "escalation", "overdue"],
        requires_file=False,
        file_types=[],
        output_type="text",
        examples_ko=["방치이슈 확인", "에스컬레이션 필요한 이슈", "장기미결 이슈"],
        phase=4,
        stability="experimental",
    ),
    "decision_logger": SkillDef(
        skill_id="decision_logger",
        name_ko="결정사항 기록",
        category="engineering",
        description_ko="회의 결정 → 이슈 YAML 자동 업데이트 (decision/due_date/status)",
        keywords_ko=["결정기록", "결정사항", "의사결정", "회의결정", "결정등록"],
        keywords_en=["decision", "decision log"],
        requires_file=False,
        file_types=[],
        output_type="text",
        examples_ko=["SEN-335 결정: HMB 전단보강 추가", "SEN-428 결정사항 PSRC 접합부 재검토"],
        phase=4,
        stability="experimental",
    ),

    # ── Phase 4B: 모니터링 & 리포팅 ──
    "lead_time_tracker": SkillDef(
        skill_id="lead_time_tracker",
        name_ko="리드타임 추적",
        category="engineering",
        description_ko="부재별 제작일정 vs 잔여시간 갭 분석 + 지연 위험 표시",
        keywords_ko=["리드타임", "납기추적", "공정추적", "크리티컬패스", "주요경로", "일정분석"],
        keywords_en=["leadtime", "lead time", "critical path"],
        requires_file=False,
        file_types=[],
        output_type="text",
        examples_ko=["리드타임 분석", "PSRC 납기추적", "크리티컬패스 확인"],
        phase=4,
        stability="experimental",
    ),
    "contractor_digest": SkillDef(
        skill_id="contractor_digest",
        name_ko="협력사별 현황",
        category="engineering",
        description_ko="source_origin별 이슈/미결/응답성 스코어카드",
        keywords_ko=["협력사현황", "업체현황", "업체별", "협력사별", "삼성현황", "센구조현황"],
        keywords_en=["contractor", "vendor status"],
        requires_file=False,
        file_types=[],
        output_type="text",
        examples_ko=["협력사현황", "센구조현황", "업체별 이슈"],
        phase=4,
        stability="experimental",
    ),
    "weekly_executive": SkillDef(
        skill_id="weekly_executive",
        name_ko="주간 경영보고",
        category="generation",
        description_ko="대시보드+리스크+파이프라인+협력사 통합 Excel 보고서",
        keywords_ko=["주간경영", "경영보고", "주간보고서", "주간현황", "위클리", "주보"],
        keywords_en=["weekly", "executive report"],
        requires_file=False,
        file_types=[],
        output_type="both",
        examples_ko=["주간경영 보고서", "경영보고 생성", "위클리 리포트"],
        phase=4,
        stability="experimental",
    ),

    # ── Phase 5: 고급 분석 ──
    "spec_checker": SkillDef(
        skill_id="spec_checker",
        name_ko="사양 검증",
        category="analysis",
        description_ko="Shop DWG OCR 결과 vs 이슈DB 사양 교차검증 (PASS/WARN/FAIL)",
        keywords_ko=["사양검증", "스펙체크", "사양확인", "규격검증", "도면검증"],
        keywords_en=["speccheck", "spec check", "verification"],
        requires_file=True,
        file_types=[".pdf", ".png", ".jpg", ".jpeg", ".dxf"],
        output_type="text",
        examples_ko=["(도면 첨부) 사양검증", "(Shop DWG 첨부) 스펙체크"],
        phase=5,
        stability="experimental",
    ),

    # ── Phase 5: 데스크톱 원격 제어 ──
    "desktop_control": SkillDef(
        skill_id="desktop_control",
        name_ko="데스크톱 제어",
        category="desktop",
        description_ko="PC 화면 확인, 프로그램 실행/제어, 스크린샷 캡처 (원격)",
        keywords_ko=[
            "화면캡처", "스크린샷", "화면보여", "데스크톱", "활성프로그램",
            "프로그램실행", "앱열어", "pc제어", "원격제어", "화면확인",
        ],
        keywords_en=["screenshot", "desktop", "screen", "remote control"],
        requires_file=False,
        file_types=[],
        output_type="both",
        examples_ko=[
            "화면 보여줘",
            "지금 뭐 열려있어?",
            "크롬 열어줘",
            "스크린샷 찍어줘",
        ],
        phase=5,
        implemented=True,
    ),

    "pdf_summary": SkillDef(
        skill_id="pdf_summary",
        name_ko="PDF 요약 생성",
        category="generation",
        description_ko="이슈/보고서를 PDF 요약 문서로 생성",
        keywords_ko=["pdf생성", "요약보고서", "pdf보고서"],
        keywords_en=["pdf generate", "summary report"],
        requires_file=False,
        file_types=[],
        output_type="file",
        examples_ko=["이슈 요약 PDF 만들어줘", "요약보고서 생성"],
        phase=3,
        implemented=False,
    ),
    "quick_calc": SkillDef(
        skill_id="quick_calc",
        name_ko="빠른 계산",
        category="utility",
        description_ko="날짜 차이, 수량 합계, 공기 계산 등",
        keywords_ko=["계산", "산출", "공기계산", "날짜계산"],
        keywords_en=["calc", "calculate"],
        requires_file=False,
        file_types=[],
        output_type="text",
        examples_ko=["2/10~3/15 공기 계산", "PSRC 수량 합계"],
        phase=3,
        implemented=False,
    ),
    # ── Phase 6: 자동화 5대 스킬 ──
    "resend_failed": SkillDef(
        skill_id="resend_failed",
        name_ko="전송실패 재전송",
        category="system",
        description_ko="전송실패된 작업 결과를 자동으로 재전송",
        keywords_ko=["재전송", "전송실패", "미전달"],
        keywords_en=["resend"],
        requires_file=False,
        file_types=[],
        output_type="text",
        examples_ko=["재전송", "전송실패 복구"],
        phase=6,
        stability="experimental",
    ),
    "health_report": SkillDef(
        skill_id="health_report",
        name_ko="시스템 헬스 리포트",
        category="system",
        description_ko="시스템 성과 리포트 (성공률, 스킬 사용량 등)",
        keywords_ko=["시스템점검", "헬스체크", "시스템현황"],
        keywords_en=["health"],
        requires_file=False,
        file_types=[],
        output_type="text",
        examples_ko=["시스템점검", "헬스체크"],
        phase=6,
        stability="experimental",
    ),
    "issue_trend": SkillDef(
        skill_id="issue_trend",
        name_ko="이슈 트렌드 대시보드",
        category="analysis",
        description_ko="PSRC 이슈 카테고리별/주간 트렌드 Excel 생성",
        keywords_ko=["이슈트렌드", "이슈대시보드", "트렌드분석"],
        keywords_en=["issue trend", "trend"],
        requires_file=False,
        file_types=[],
        output_type="both",
        examples_ko=["이슈트렌드", "PSRC 트렌드 분석"],
        phase=6,
        stability="experimental",
    ),
    "kakao_daily_summary": SkillDef(
        skill_id="kakao_daily_summary",
        name_ko="카톡 업무 요약",
        category="kakao_live",
        description_ko="카카오톡 업무방 대화 핵심 요약 리포트",
        keywords_ko=["카톡요약리포트", "카톡일일요약", "카톡업무요약"],
        keywords_en=["kakao summary report"],
        requires_file=False,
        file_types=[],
        output_type="both",
        examples_ko=["카톡요약리포트", "카톡 업무 요약"],
        phase=6,
        stability="experimental",
    ),
    "quantity_monitor": SkillDef(
        skill_id="quantity_monitor",
        name_ko="물량 변동 감시",
        category="engineering",
        description_ko="선제작 물량 기준 대비 변동률 보고",
        keywords_ko=["물량감시", "물량변동", "물량모니터"],
        keywords_en=["quantity monitor"],
        requires_file=False,
        file_types=[],
        output_type="text",
        examples_ko=["물량감시", "물량 변동 확인"],
        phase=6,
        stability="experimental",
    ),
    "traceability_map": SkillDef(
        skill_id="traceability_map",
        name_ko="이슈-도면-제작 연계추적",
        category="engineering",
        description_ko="이슈↔도면↔제작 크로스-레퍼런스 맵 생성",
        keywords_ko=["연계추적", "추적맵", "트레이서빌리티", "연계분석"],
        keywords_en=["traceability"],
        requires_file=False,
        file_types=[],
        output_type="both",
        examples_ko=["연계추적", "이슈-도면 연계 분석"],
        phase=6,
        stability="experimental",
    ),
}


# ═══════════════════════════════════════════════════════════════
#  도움말 및 검색
# ═══════════════════════════════════════════════════════════════

CATEGORY_LABELS = {
    "analysis": "📊 분석",
    "generation": "📝 생성",
    "intelligence": "🧠 인텔리전스",
    "utility": "🔧 유틸리티",
    "google": "🌐 Google 연동",
    "email": "📧 이메일",
    "kakao": "💬 카카오톡",
    "kakao_live": "💬 카카오톡 실시간",
    "engineering": "🏗️ 구조 엔지니어링",
    "desktop": "🖥️ 데스크톱 제어",
    "system": "⚙️ 시스템 관리",
}

CATEGORY_ORDER = ["utility", "system", "email", "google", "kakao", "kakao_live", "engineering", "desktop", "analysis", "intelligence", "generation"]


def get_skill_help_text() -> str:
    """전체 스킬 도움말 텍스트 생성."""
    lines = [
        "🤖 P5 프로젝트 스킬 목록",
        "━" * 30,
        "",
    ]

    for cat in CATEGORY_ORDER:
        cat_skills = [s for s in SKILLS.values() if s.category == cat]
        if not cat_skills:
            continue

        lines.append(f"{CATEGORY_LABELS.get(cat, cat)}")
        lines.append("─" * 25)

        for skill in cat_skills:
            status = "✅" if skill.implemented else "🔜"
            file_hint = " 📎" if skill.requires_file else ""
            lines.append(f"  {status} {skill.name_ko}{file_hint}")
            lines.append(f"     └ {skill.description_ko}")
            kw_str = ", ".join(skill.keywords_ko[:3])
            lines.append(f"     키워드: {kw_str}")
            if skill.examples_ko:
                lines.append(f'     예시: "{skill.examples_ko[0]}"')
            lines.append("")

    lines.append("━" * 30)
    lines.append("📎 = 파일 첨부 필요 | 🔜 = 준비 중")
    lines.append("💡 파일만 보내도 자동 분석 (PDF→PDF분석, Excel→엑셀분석)")

    return "\n".join(lines)


def get_skill_by_id(skill_id: str) -> Optional[SkillDef]:
    """스킬 ID로 조회."""
    return SKILLS.get(skill_id)


def get_skills_by_category(category: str) -> List[SkillDef]:
    """카테고리별 스킬 목록."""
    return [s for s in SKILLS.values() if s.category == category]


def get_implemented_skills() -> List[SkillDef]:
    """구현 완료된 스킬 목록."""
    return [s for s in SKILLS.values() if s.implemented]


def get_stable_skills() -> List[SkillDef]:
    """stability='stable'인 스킬 목록."""
    return [s for s in SKILLS.values() if s.stability == "stable"]


def get_experimental_skills() -> List[SkillDef]:
    """stability='experimental'인 스킬 목록."""
    return [s for s in SKILLS.values() if s.stability == "experimental"]


def find_skill_by_keyword(keyword: str) -> Optional[SkillDef]:
    """키워드로 스킬 검색 (가장 긴 매칭 우선)."""
    keyword_lower = keyword.lower()
    best_match: Optional[SkillDef] = None
    best_len = 0

    for skill in SKILLS.values():
        if not skill.implemented:
            continue
        all_keywords = skill.keywords_ko + skill.keywords_en
        for kw in all_keywords:
            if kw.lower() in keyword_lower and len(kw) > best_len:
                best_match = skill
                best_len = len(kw)

    return best_match
