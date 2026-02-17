#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
인텔리전스 스킬 모듈

- email_response: 수신 이메일 답신 방향 제시
- fabrication_status: 제작/납품 현황 매트릭스
- meeting_prep: 회의 안건 및 준비자료 구성
"""

from __future__ import annotations

import os
import re
import traceback
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from scripts.telegram.skill_utils import (
    load_vault_issues,
    search_issues,
    get_issue_by_id,
    detect_sen_refs,
    truncate_text,
    format_matrix_text,
    classify_stages,
    get_stage_icon,
    FABRICATION_CATEGORIES,
    FABRICATION_STAGES,
    PRIORITY_URGENCY,
    CATEGORY_IMPACT,
    CONFIG_DIR,
)


# ═══════════════════════════════════════════════════════════════
#  email_response — 이메일 답신 방향
# ═══════════════════════════════════════════════════════════════

def run_email_response(context: dict) -> dict:
    """
    수신 이메일에 대한 답신 전략 및 초안 제안.

    1. 지시 텍스트에서 이메일 내용 추출
    2. SEN 이슈 교차 참조
    3. 발신자/수신자 가중치 확인
    4. 답신 전략 생성: 톤, 핵심 포인트, 액션아이템
    """
    send_progress = context.get("send_progress", lambda x: None)
    combined = context.get("combined", {})
    instruction = combined.get("combined_instruction", "")
    memories = context.get("memories", [])

    send_progress("📧 이메일 답신 방향 분석 중...")

    # 이메일 내용 추출 (지시 텍스트에서 전달된 메일 본문)
    email_content = _extract_email_content(instruction)

    if not email_content:
        return {
            "result_text": (
                "⚠️ 답신할 이메일 내용을 찾을 수 없습니다.\n\n"
                "사용법:\n"
                "1. 이메일을 전달(포워드)하고 \"답신 방향 잡아줘\" 추가\n"
                "2. 이메일 내용을 복사해서 \"이 메일에 회신\" 추가"
            ),
            "files": [],
        }

    # SEN 이슈 교차 참조
    sen_refs = detect_sen_refs(email_content)
    related_issues = []
    for ref in sen_refs[:5]:
        issue = get_issue_by_id(ref)
        if issue:
            related_issues.append(issue)

    # 발신자 분석
    sender = _extract_sender(email_content)
    urgency = _assess_email_urgency(email_content)

    # 답신 전략 생성
    lines = [
        "📧 이메일 답신 방향",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
    ]

    if sender:
        lines.append(f"📨 발신자: {sender}")
    lines.append(f"⚡ 긴급도: {urgency}")
    lines.append("")

    # 핵심 요청사항 분석
    requests = _extract_action_requests(email_content)
    if requests:
        lines.append("📋 감지된 요청사항:")
        for i, req in enumerate(requests, 1):
            lines.append(f"  {i}. {req}")
        lines.append("")

    # 관련 이슈
    if related_issues:
        lines.append(f"📌 관련 P5 이슈 ({len(related_issues)}건):")
        for issue in related_issues:
            iid = issue.get("issue_id", "?")
            title = issue.get("title", "?")
            status = issue.get("status", "?")
            lines.append(f"  • {iid}: {title} [{status}]")
        lines.append("")

    # 답신 전략
    lines.append("💡 답신 전략:")
    tone = _suggest_reply_tone(urgency, sender)
    lines.append(f"  • 톤: {tone}")

    # 핵심 포인트 제안
    lines.append("\n📝 답신 포인트:")
    points = _generate_reply_points(email_content, requests, related_issues)
    for point in points:
        lines.append(f"  → {point}")

    # 액션아이템
    actions = _generate_action_items(requests, related_issues)
    if actions:
        lines.append("\n⚡ 후속 액션아이템:")
        for action in actions:
            lines.append(f"  □ {action}")

    return {
        "result_text": truncate_text("\n".join(lines)),
        "files": [],
    }


def _extract_email_content(instruction: str) -> str:
    """지시 텍스트에서 이메일 본문 추출."""
    # 답신 관련 키워드 이후의 텍스트를 이메일 내용으로 간주
    patterns = [
        r"(?:답신|답장|회신|메일답변|답변방향)[^:]*[:\s]+(.*)",
        r"(?:이\s*메일|아래\s*메일|다음\s*메일)[^:]*[:\s]+(.*)",
    ]
    for pattern in patterns:
        match = re.search(pattern, instruction, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()

    # 키워드를 제거한 나머지가 충분히 길면 이메일로 간주
    cleaned = instruction
    for kw in ["답신", "답장", "회신", "메일답변", "답변방향", "방향", "잡아줘", "만들어줘", "해줘"]:
        cleaned = cleaned.replace(kw, "")
    cleaned = cleaned.strip()

    if len(cleaned) > 30:
        return cleaned

    return ""


def _extract_sender(text: str) -> str:
    """이메일에서 발신자 추출."""
    patterns = [
        r"(?:From|보낸\s*사람|발신)[:\s]+([^\n<]+)",
        r"([가-힣]{2,4})\s*(?:수석|프로|소장|부장|과장|대리|팀장|실장)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    return ""


def _assess_email_urgency(text: str) -> str:
    """이메일 긴급도 평가."""
    urgent_keywords = ["긴급", "즉시", "오늘까지", "당일", "urgent", "asap", "today"]
    high_keywords = ["내일까지", "금주", "조속", "빠른", "확인필요"]

    text_lower = text.lower()
    if any(kw in text_lower for kw in urgent_keywords):
        return "🔴 긴급"
    if any(kw in text_lower for kw in high_keywords):
        return "🟡 높음"
    return "🟢 보통"


def _extract_action_requests(text: str) -> List[str]:
    """이메일에서 요청/액션 사항 추출."""
    requests = []
    action_patterns = [
        r"(?:요청|부탁|확인|검토|회신|송부|제출|보내)[^.。\n]{5,50}[.。]?",
        r"(?:해\s*주|하여\s*주|바랍니다|부탁드립니다)[^.。\n]{0,50}",
        r"(?:필요합니다|요망|요청합니다)[^.。\n]{0,50}",
    ]
    for pattern in action_patterns:
        matches = re.findall(pattern, text)
        for m in matches:
            cleaned = m.strip()
            if len(cleaned) > 10 and cleaned not in requests:
                requests.append(cleaned)

    return requests[:5]


def _suggest_reply_tone(urgency: str, sender: str) -> str:
    """답신 톤 제안."""
    if "긴급" in urgency:
        return "즉각적이고 구체적인 회신 (오늘 내 회신 권장)"
    if "높음" in urgency:
        return "신속하고 전문적인 회신 (1-2일 내 회신)"
    return "정중하고 체계적인 회신"


def _generate_reply_points(
    content: str, requests: List[str], issues: List[Dict]
) -> List[str]:
    """답신 핵심 포인트 생성."""
    points = []
    if requests:
        points.append(f"요청사항 {len(requests)}건에 대한 대응 현황 명시")
    if issues:
        points.append(f"관련 이슈 {len(issues)}건 참조하여 현황 공유")
    points.append("예상 완료 시점 또는 다음 단계 일정 제시")
    points.append("추가 필요 자료/정보 있으면 역요청")
    return points


def _generate_action_items(
    requests: List[str], issues: List[Dict]
) -> List[str]:
    """후속 액션아이템 생성."""
    actions = []
    for req in requests[:3]:
        actions.append(f"요청사항 처리: {req[:40]}...")
    for issue in issues[:2]:
        iid = issue.get("issue_id", "?")
        actions.append(f"{iid} 이슈 현황 업데이트")
    return actions


# ═══════════════════════════════════════════════════════════════
#  fabrication_status — 제작/납품 현황
# ═══════════════════════════════════════════════════════════════

def run_fabrication_status(context: dict) -> dict:
    """
    부재별 제작 단계 및 납품 현황 매트릭스.

    1. 볼트 이슈에서 제작 관련 카테고리 필터
    2. 부재 타입별 현황 분류
    3. 단계별 매트릭스 텍스트 생성
    """
    send_progress = context.get("send_progress", lambda x: None)
    combined = context.get("combined", {})
    instruction = combined.get("combined_instruction", "")

    send_progress("🏭 제작/납품 현황 분석 중...")

    # 이슈 로딩 — 제작 관련 필터
    all_issues = load_vault_issues()
    fab_issues = [
        i for i in all_issues
        if i.get("category", "").lower() in FABRICATION_CATEGORIES
        or any(
            kw in i.get("title", "").lower()
            for kw in ["제작", "납품", "shop", "가공", "반입", "부재"]
        )
    ]

    if not fab_issues:
        return {
            "result_text": (
                "📋 제작/납품 관련 이슈가 없습니다.\n\n"
                "현재 P5 볼트에 등록된 제작 관련 카테고리:\n"
                f"  {', '.join(FABRICATION_CATEGORIES)}"
            ),
            "files": [],
        }

    # 특정 부재 타입 필터 (지시에 포함된 경우)
    target_type = _detect_member_type(instruction)

    # 부재 타입별 분류
    type_groups: Dict[str, List[Dict]] = {}
    for issue in fab_issues:
        cat = issue.get("category", "기타").upper()
        type_groups.setdefault(cat, []).append(issue)

    if target_type:
        # 특정 타입만 표시
        filtered = {k: v for k, v in type_groups.items() if target_type.upper() in k}
        if filtered:
            type_groups = filtered

    # 매트릭스 생성
    lines = [
        "🏭 제작/납품 현황 매트릭스",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        f"📅 기준: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"📊 총 이슈: {len(fab_issues)}건",
        "",
    ]

    # 부재 타입별 현황
    for member_type, issues in sorted(type_groups.items()):
        lines.append(f"▸ {member_type} ({len(issues)}건)")
        lines.append("─" * 30)

        # 단계별 분류
        stages = classify_stages(issues)
        for stage_name, stage_issues in stages.items():
            if stage_issues:
                count = len(stage_issues)
                status_icon = get_stage_icon(stage_name)
                lines.append(f"  {status_icon} {stage_name}: {count}건")
                for si in stage_issues[:3]:
                    iid = si.get("issue_id", "?")
                    title = si.get("title", "?")[:30]
                    prio = si.get("priority", "?")
                    lines.append(f"    • {iid}: {title} [{prio}]")
                if len(stage_issues) > 3:
                    lines.append(f"    ... 외 {len(stage_issues) - 3}건")

        lines.append("")

    # 요약 통계
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("📊 현황 요약")

    total_critical = sum(
        1 for i in fab_issues
        if i.get("priority", "").lower() in ("critical", "high")
    )
    total_overdue = sum(
        1 for i in fab_issues
        if _is_overdue(i)
    )

    lines.append(f"  • 긴급/높음: {total_critical}건")
    if total_overdue > 0:
        lines.append(f"  • ⚠️ 기한 초과: {total_overdue}건")

    # 주요 액션아이템
    lines.append("\n⚡ 대응 필요:")
    critical_items = [
        i for i in fab_issues
        if i.get("priority", "").lower() == "critical"
    ]
    for ci in critical_items[:3]:
        lines.append(f"  🔴 {ci.get('issue_id', '?')}: {ci.get('title', '?')[:40]}")

    return {
        "result_text": truncate_text("\n".join(lines)),
        "files": [],
    }


def _detect_member_type(instruction: str) -> Optional[str]:
    """지시에서 부재 타입 감지."""
    types = ["psrc", "hmb", "pc", "ep", "fcc", "pleg"]
    for t in types:
        if t in instruction.lower():
            return t
    return None


# _classify_stages, _get_stage_icon → skill_utils.py 로 이동됨
# from skill_utils import classify_stages, get_stage_icon


def _is_overdue(issue: Dict) -> bool:
    """마감일 초과 여부 확인."""
    due = issue.get("due_date", "")
    if not due:
        return False
    try:
        due_date = datetime.strptime(str(due)[:10], "%Y-%m-%d")
        return due_date < datetime.now()
    except (ValueError, TypeError):
        return False


# ═══════════════════════════════════════════════════════════════
#  meeting_prep — 회의 준비
# ═══════════════════════════════════════════════════════════════

def run_meeting_prep(context: dict) -> dict:
    """
    회의 안건 및 사전 준비자료 구성.

    1. 회의 타입 감지 (주간/구조검토/설계협의)
    2. 핵심 이슈 수집 (Critical/High + 마감 임박)
    3. 안건 구성: 시간 배분, 참조 자료, 사전 준비사항
    """
    send_progress = context.get("send_progress", lambda x: None)
    combined = context.get("combined", {})
    instruction = combined.get("combined_instruction", "")

    send_progress("📋 회의 준비 자료 생성 중...")

    # 회의 타입 감지
    meeting_type = _detect_meeting_type(instruction)

    # 이슈 데이터 로딩
    all_issues = load_vault_issues()

    # 핵심 이슈 (Critical/High)
    critical_issues = [
        i for i in all_issues
        if i.get("priority", "").lower() in ("critical", "high")
        and i.get("status", "").lower() != "closed"
    ]

    # 마감 7일 이내
    upcoming = _get_upcoming_deadlines(all_issues, days=7)

    # 최근 7일 신규 이슈
    recent_new = load_vault_issues(filters={"since_days": 7})

    lines = [
        f"📋 {meeting_type} 준비 자료",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        f"📅 일시: {datetime.now().strftime('%Y-%m-%d')}",
        f"📊 전체 이슈: {len(all_issues)}건 | 긴급: {len(critical_issues)}건",
        "",
    ]

    # 1. 안건 1: 긴급 이슈
    lines.append("━━ 안건 1: 긴급 이슈 검토 ━━")
    if critical_issues:
        for issue in critical_issues[:5]:
            iid = issue.get("issue_id", "?")
            title = issue.get("title", "?")
            cat = issue.get("category", "?")
            owner = issue.get("owner", "미지정")
            lines.append(f"  🔴 {iid}: {title}")
            lines.append(f"     카테고리: {cat} | 담당: {owner}")
    else:
        lines.append("  ✅ 긴급 이슈 없음")
    lines.append("")

    # 2. 안건 2: 마감 임박
    lines.append("━━ 안건 2: 마감 임박 항목 ━━")
    if upcoming:
        for issue in upcoming[:5]:
            iid = issue.get("issue_id", "?")
            title = issue.get("title", "?")
            due = issue.get("due_date", "?")
            lines.append(f"  ⏰ {iid}: {title} (마감: {due})")
    else:
        lines.append("  ✅ 7일 내 마감 항목 없음")
    lines.append("")

    # 3. 안건 3: 신규 이슈 보고
    lines.append("━━ 안건 3: 금주 신규 이슈 ━━")
    if recent_new:
        lines.append(f"  신규 {len(recent_new)}건:")
        for issue in recent_new[:5]:
            iid = issue.get("issue_id", "?")
            title = issue.get("title", "?")
            lines.append(f"  • {iid}: {title}")
    else:
        lines.append("  없음")
    lines.append("")

    # 4. 회의 타입별 추가 안건
    if meeting_type == "주간회의":
        lines.append("━━ 안건 4: 금주 계획 ━━")
        lines.append("  • 주요 마일스톤 확인")
        lines.append("  • 협력사 이슈 검토")
        lines.append("  • 다음 주 중점 사항 논의")
    elif meeting_type == "구조검토회의":
        struct_issues = [i for i in all_issues if "구조" in i.get("category", "")]
        lines.append("━━ 안건 4: 구조 이슈 현황 ━━")
        lines.append(f"  구조 관련 이슈: {len(struct_issues)}건")
        for si in struct_issues[:5]:
            lines.append(f"  • {si.get('issue_id', '?')}: {si.get('title', '?')}")
    elif meeting_type == "설계협의":
        design_issues = [i for i in all_issues if "설계" in i.get("category", "")]
        lines.append("━━ 안건 4: 설계 이슈 현황 ━━")
        lines.append(f"  설계 관련 이슈: {len(design_issues)}건")
        for di in design_issues[:5]:
            lines.append(f"  • {di.get('issue_id', '?')}: {di.get('title', '?')}")
    lines.append("")

    # 5. 사전 준비사항
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("📌 사전 준비사항:")
    lines.append("  □ 긴급 이슈 대응 현황 확인")
    lines.append("  □ 마감 임박 항목 진행률 체크")
    lines.append("  □ 금주 목표 대비 실적 정리")
    if critical_issues:
        lines.append(f"  □ {critical_issues[0].get('issue_id', '')} 이슈 상세 자료 준비")

    return {
        "result_text": truncate_text("\n".join(lines)),
        "files": [],
    }


def _detect_meeting_type(instruction: str) -> str:
    """회의 타입 감지."""
    inst_lower = instruction.lower()
    if any(kw in inst_lower for kw in ["주간", "weekly", "정기"]):
        return "주간회의"
    if any(kw in inst_lower for kw in ["구조", "structural", "검토"]):
        return "구조검토회의"
    if any(kw in inst_lower for kw in ["설계", "design", "협의"]):
        return "설계협의"
    return "주간회의"  # 기본값


def _get_upcoming_deadlines(
    issues: List[Dict], days: int = 7
) -> List[Dict]:
    """마감일 N일 이내 이슈 추출."""
    now = datetime.now()
    cutoff = now + timedelta(days=days)
    upcoming = []

    for issue in issues:
        if issue.get("status", "").lower() == "closed":
            continue
        due = issue.get("due_date", "")
        if not due:
            continue
        try:
            due_date = datetime.strptime(str(due)[:10], "%Y-%m-%d")
            if now <= due_date <= cutoff:
                upcoming.append(issue)
        except (ValueError, TypeError):
            pass

    return sorted(
        upcoming,
        key=lambda x: x.get("due_date", "9999-12-31"),
    )
