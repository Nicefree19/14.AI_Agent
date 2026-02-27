#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
구조 엔지니어링 스킬 모듈

P5 복합동 프로젝트 특화 의사결정 지원 스킬.

Phase 4A:
  - cascade_analyzer: 이슈 연쇄/파급효과 분석
  - stale_hunter: 방치 이슈 탐지 + 에스컬레이션 제안
  - decision_logger: 회의 결정사항 기록 → 이슈 업데이트

Phase 4B:
  - lead_time_tracker: 부재별 리드타임 vs 잔여시간 갭
  - contractor_digest: 협력사별 현황 스코어카드
  - weekly_executive: 주간 경영보고 통합 Excel

Phase 5:
  - spec_checker: Shop DWG OCR → 이슈DB 사양 교차검증
"""

from __future__ import annotations

import os
import re
import traceback
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from scripts.telegram.skill_utils import (
    load_vault_issues,
    search_issues,
    get_issue_by_id,
    detect_sen_refs,
    detect_drawing_refs,
    classify_stages,
    get_stage_icon,
    format_issue_detail,
    create_excel_workbook,
    FABRICATION_CATEGORIES,
    FABRICATION_STAGES,
    PRIORITY_URGENCY,
    CATEGORY_IMPACT,
)

# ═══════════════════════════════════════════════════════════════
#  공통 상수 & 헬퍼
# ═══════════════════════════════════════════════════════════════

# 구조 인터페이스 종속 체인 (방향 그래프)
_INTERFACE_CHAIN: Dict[str, List[str]] = {
    "psrc":   ["hmb", "구조접합"],
    "hmb":    ["pc연동", "구조접합"],
    "pc연동": ["구조접합", "ep"],
    "구조접합": ["ep"],
    "ep":     [],
}

# 부재별 리드타임 (일) — 도메인 지식
_LEAD_TIMES: Dict[str, Dict[str, int]] = {
    "psrc": {"shop_dwg": 14, "fabrication": 75, "delivery": 7, "install": 3},
    "hmb":  {"shop_dwg": 10, "fabrication": 37, "delivery": 5, "install": 2},
    "ep":   {"shop_dwg":  7, "fabrication": 21, "delivery": 3, "install": 1},
    "pc":   {"shop_dwg": 10, "fabrication": 45, "delivery": 5, "install": 2},
}

# 협력사 명칭 정규화 매핑
_ORG_NAMES: Dict[str, str] = {
    "삼성":     "삼성 E&A",
    "samsung":  "삼성 E&A",
    "센구조":   "센구조",
    "센코어":   "센코어테크",
    "이앤디몰": "이앤디몰",
    "endmall":  "이앤디몰",
    "삼우":     "삼우",
    "samwoo":   "삼우",
    "정림":     "정림건축",
    "ena":      "ENA",
}

# 리드타임 단계 순서 (classify_stages와 정렬)
_STAGE_ORDER = ["설계검토", "Shop DWG", "제작중", "납품", "시공"]

# 단계별 잔여 리드타임 계산용 인덱스
_STAGE_IDX = {s: i for i, s in enumerate(_STAGE_ORDER)}

# 리드타임 단계 키 매핑 (FABRICATION_STAGES → _LEAD_TIMES 키)
_STAGE_LT_KEY = {
    "설계검토": "shop_dwg",
    "Shop DWG": "shop_dwg",
    "제작중":   "fabrication",
    "납품":     "delivery",
    "시공":     "install",
}


def _get_open_issues() -> List[Dict]:
    """open/in_progress 이슈만 로드."""
    all_issues = load_vault_issues()
    return [
        i for i in all_issues
        if i.get("status", "").lower() not in ("closed", "resolved")
    ]


def _parse_due_date(issue: Dict) -> Optional[datetime]:
    """이슈의 due_date를 datetime으로 파싱."""
    due = issue.get("due_date", "")
    if not due:
        return None
    try:
        if isinstance(due, datetime):
            return due
        return datetime.strptime(str(due).strip()[:10], "%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def _parse_created_date(issue: Dict) -> Optional[datetime]:
    """이슈의 created를 datetime으로 파싱."""
    created = issue.get("created", "")
    if not created:
        return None
    try:
        if isinstance(created, datetime):
            return created
        return datetime.strptime(str(created).strip()[:10], "%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def _days_since(dt: Optional[datetime]) -> int:
    """datetime으로부터 경과 일수. None이면 0."""
    if not dt:
        return 0
    return max(0, (datetime.now() - dt).days)


def _detect_member_type(issue: Dict) -> Optional[str]:
    """이슈에서 부재 타입 감지."""
    text = f"{issue.get('title', '')} {issue.get('category', '')} {issue.get('_body', '')}".lower()
    for t in ["psrc", "hmb", "pc", "ep"]:
        if t in text:
            return t
    return None


def _normalize_org(name: str) -> str:
    """조직명 정규화."""
    name_lower = name.lower().strip()
    for key, canonical in _ORG_NAMES.items():
        if key in name_lower:
            return canonical
    return name.strip()


# ═══════════════════════════════════════════════════════════════
#  스킬 1: cascade_analyzer — 이슈 연쇄/파급효과 분석
# ═══════════════════════════════════════════════════════════════

def _build_dependency_graph(
    issues: List[Dict], target_id: str
) -> Dict[str, Any]:
    """
    타겟 이슈를 기준으로 종속관계 그래프 구축.

    링크 유형:
      - zone: 동일 zone (물리적 인접)
      - interface: 구조 인터페이스 체인 종속
      - contractor: 동일 source_origin (같은 협력사)
      - reference: _body/action_plan에서 SEN-ID 상호참조
      - temporal: due_date 14일 이내 시간적 중첩
    """
    target = get_issue_by_id(target_id)
    if not target:
        return {"target": None, "links": []}

    target_zone = (target.get("zone") or "").lower()
    target_cat = (target.get("category") or "").lower()
    target_org = (target.get("source_origin") or "").lower()
    target_due = _parse_due_date(target)
    target_body = f"{target.get('_body', '')} {target.get('action_plan', '')}"

    links: List[Dict[str, Any]] = []

    for issue in issues:
        iid = issue.get("issue_id", "")
        if iid == target_id:
            continue

        link_types: List[str] = []
        weight = 0.0

        # 1. Zone 중첩
        issue_zone = (issue.get("zone") or "").lower()
        if target_zone and issue_zone and target_zone == issue_zone:
            link_types.append("zone")
            weight += 0.3

        # 2. 인터페이스 체인
        issue_cat = (issue.get("category") or "").lower()
        chain_downstream = _INTERFACE_CHAIN.get(target_cat, [])
        chain_upstream = [
            k for k, v in _INTERFACE_CHAIN.items() if target_cat in v
        ]
        if issue_cat in chain_downstream:
            link_types.append("interface_downstream")
            weight += 0.5
        elif issue_cat in chain_upstream:
            link_types.append("interface_upstream")
            weight += 0.4

        # 3. 동일 협력사
        issue_org = (issue.get("source_origin") or "").lower()
        if target_org and issue_org and target_org == issue_org:
            link_types.append("contractor")
            weight += 0.2

        # 4. SEN-ID 상호참조
        issue_body = f"{issue.get('_body', '')} {issue.get('action_plan', '')}"
        if target_id in issue_body:
            link_types.append("reference")
            weight += 0.6
        if iid and iid in target_body:
            link_types.append("referenced_by")
            weight += 0.5

        # 5. 시간적 중첩 (14일 이내)
        issue_due = _parse_due_date(issue)
        if target_due and issue_due:
            gap = abs((target_due - issue_due).days)
            if gap <= 14:
                link_types.append("temporal")
                weight += 0.3 * (1 - gap / 14)

        if not link_types:
            continue

        # 가중치 보정: 카테고리 임팩트 × 우선순위
        cat_impact = CATEGORY_IMPACT.get(issue_cat, 0.5)
        prio_str = (issue.get("priority") or "medium").lower()
        prio_mult = {
            "critical": 2.0, "high": 1.5, "medium": 1.0, "low": 0.5
        }.get(prio_str, 1.0)
        final_weight = weight * cat_impact * prio_mult

        links.append({
            "issue_id": iid,
            "title": issue.get("title", ""),
            "priority": issue.get("priority", ""),
            "category": issue.get("category", ""),
            "zone": issue.get("zone", ""),
            "link_types": link_types,
            "weight": round(final_weight, 3),
        })

    # 가중치 내림차순 정렬
    links.sort(key=lambda x: x["weight"], reverse=True)
    return {"target": target, "links": links}


def run_cascade_analyzer(context: dict) -> dict:
    """
    이슈 연쇄 분석.

    지시에서 SEN-ID 또는 카테고리 키워드를 감지하여
    종속관계 그래프 + 파급효과 점수 + 조치 우선순위 출력.
    """
    send_progress = context.get("send_progress", lambda x: None)
    combined = context.get("combined", {})
    instruction = combined.get("combined_instruction", "")

    send_progress("🔗 이슈 연쇄 분석 시작...")

    try:
        all_issues = _get_open_issues()
        if not all_issues:
            return {"result_text": "⚠️ 분석할 이슈가 없습니다.", "files": []}

        # 타겟 이슈 식별
        sen_refs = detect_sen_refs(instruction)
        target_id = sen_refs[0] if sen_refs else None

        # SEN-ID 없으면 카테고리로 검색
        if not target_id:
            for cat in CATEGORY_IMPACT:
                if cat in instruction.lower():
                    cat_issues = [
                        i for i in all_issues
                        if cat in (i.get("category") or "").lower()
                    ]
                    if cat_issues:
                        # 가장 높은 우선순위 이슈 선택
                        cat_issues.sort(
                            key=lambda x: PRIORITY_URGENCY.get(
                                (x.get("priority") or "medium").lower(), 0.5
                            ),
                            reverse=True,
                        )
                        target_id = cat_issues[0].get("issue_id")
                        break

        if not target_id:
            return {
                "result_text": (
                    "⚠️ 분석 대상을 특정할 수 없습니다.\n\n"
                    "사용법:\n"
                    "• \"SEN-428 연쇄분석\"\n"
                    "• \"PSRC 파급효과\"\n"
                    "• \"HMB 영향분석\""
                ),
                "files": [],
            }

        send_progress(f"🔍 {target_id} 종속관계 스캔 중...")
        graph = _build_dependency_graph(all_issues, target_id)
        target = graph["target"]
        links = graph["links"]

        if not target:
            return {
                "result_text": f"⚠️ {target_id} 이슈를 찾을 수 없습니다.",
                "files": [],
            }

        # 결과 포맷팅
        lines = [
            f"🔗 이슈 연쇄 분석: {target_id}",
            "━━━━━━━━━━━━━━━━━━━━━━━━",
            f"📌 대상: {target.get('title', '')}",
            f"   카테고리: {target.get('category', '')} | "
            f"우선순위: {target.get('priority', '')} | "
            f"zone: {target.get('zone', '')}",
            "",
        ]

        if not links:
            lines.append("✅ 직접 연관된 이슈가 없습니다.")
        else:
            # 연쇄 리스크 점수 (상위 5건 가중치 합)
            cascade_score = sum(l["weight"] for l in links[:5])
            risk_level = (
                "🔴 높음" if cascade_score >= 3.0
                else "🟡 보통" if cascade_score >= 1.5
                else "🟢 낮음"
            )
            lines.append(f"📊 연쇄 리스크 점수: {cascade_score:.1f} {risk_level}")
            lines.append(f"🔢 연관 이슈 수: {len(links)}건")
            lines.append("")

            # Top 5 영향 이슈
            lines.append("▸ Top 5 영향 이슈:")
            lines.append("─" * 30)
            for i, link in enumerate(links[:5], 1):
                link_str = ", ".join(link["link_types"])
                lines.append(
                    f"  {i}. {link['issue_id']}: "
                    f"{link['title'][:30]}"
                )
                lines.append(
                    f"     [{link['priority']}] "
                    f"가중치: {link['weight']:.2f} "
                    f"({link_str})"
                )

            # 종속 유형별 요약
            lines.append("")
            lines.append("▸ 종속 유형별 분포:")
            type_counts: Dict[str, int] = {}
            for link in links:
                for lt in link["link_types"]:
                    type_counts[lt] = type_counts.get(lt, 0) + 1
            type_labels = {
                "zone": "🏗️ 물리적 인접",
                "interface_downstream": "⬇️ 하류 인터페이스",
                "interface_upstream": "⬆️ 상류 인터페이스",
                "contractor": "🏢 동일 협력사",
                "reference": "🔗 참조됨",
                "referenced_by": "🔗 참조함",
                "temporal": "⏰ 시간 중첩",
            }
            for lt, count in sorted(
                type_counts.items(), key=lambda x: x[1], reverse=True
            ):
                label = type_labels.get(lt, lt)
                lines.append(f"  {label}: {count}건")

            # 조치 권고
            lines.append("")
            lines.append("▸ 조치 우선순위:")
            for i, link in enumerate(links[:3], 1):
                prio = link["priority"]
                icon = "🔴" if prio == "critical" else "🟡" if prio == "high" else "⚪"
                lines.append(
                    f"  {icon} {i}. {link['issue_id']} "
                    f"({', '.join(link['link_types'][:2])}) — "
                    f"즉시 영향 확인 필요"
                )

        return {"result_text": "\n".join(lines), "files": []}

    except Exception as e:
        return {
            "result_text": f"❌ 연쇄 분석 오류: {e}\n{traceback.format_exc()[:500]}",
            "files": [],
        }


# ═══════════════════════════════════════════════════════════════
#  스킬 2: stale_hunter — 방치 이슈 탐지
# ═══════════════════════════════════════════════════════════════

def _calculate_staleness(issue: Dict) -> float:
    """
    방치 점수 산출 (0~10).

    가중치:
      - 마지막 업데이트 이후 일수 (3)
      - due_date 초과 일수 (3, 주당 +1)
      - action_plan 있으나 decision 없음 (2)
      - owner 미배정 (1)
    우선순위 배수: critical ×2.0, high ×1.5
    """
    score = 0.0

    # 1. 업데이트 없는 일수 — created or modified 기준
    created = _parse_created_date(issue)
    age_days = _days_since(created)
    if age_days > 14:
        score += min(3.0, (age_days - 14) / 10)

    # 2. due_date 초과
    due = _parse_due_date(issue)
    if due:
        overdue_days = (datetime.now() - due).days
        if overdue_days > 0:
            score += min(3.0, overdue_days / 7)

    # 3. action_plan 있으나 decision 없음
    has_action = bool(issue.get("action_plan", "").strip())
    has_decision = bool(issue.get("decision", "").strip())
    if has_action and not has_decision:
        score += 2.0

    # 4. owner 미배정
    if not issue.get("owner", "").strip():
        score += 1.0

    # 우선순위 배수
    prio = (issue.get("priority") or "medium").lower()
    multiplier = {"critical": 2.0, "high": 1.5, "medium": 1.0, "low": 0.7}.get(
        prio, 1.0
    )
    return min(10.0, score * multiplier)


def run_stale_hunter(context: dict) -> dict:
    """
    방치 이슈 탐지.

    모든 open 이슈의 방치 점수를 산출하고
    3개 섹션(긴급 에스컬레이션 / 표류 / 무주)으로 분류.
    """
    send_progress = context.get("send_progress", lambda x: None)

    send_progress("🔎 방치 이슈 스캔 중...")

    try:
        open_issues = _get_open_issues()
        if not open_issues:
            return {"result_text": "✅ 열린 이슈가 없습니다.", "files": []}

        # 방치 점수 산출
        scored: List[Tuple[float, Dict]] = []
        for issue in open_issues:
            s = _calculate_staleness(issue)
            scored.append((s, issue))
        scored.sort(key=lambda x: x[0], reverse=True)

        # 3개 섹션 분류
        urgent: List[Tuple[float, Dict]] = []       # 🔴
        drifting: List[Tuple[float, Dict]] = []     # 🟡
        unowned: List[Tuple[float, Dict]] = []      # ⚪

        for s, issue in scored:
            due = _parse_due_date(issue)
            prio = (issue.get("priority") or "medium").lower()
            is_overdue = due and (datetime.now() - due).days > 0
            is_high = prio in ("critical", "high")
            no_owner = not issue.get("owner", "").strip()

            if is_overdue and is_high:
                urgent.append((s, issue))
            elif s >= 3.0:
                drifting.append((s, issue))
            elif no_owner:
                unowned.append((s, issue))

        lines = [
            "🔎 방치 이슈 탐지 결과",
            "━━━━━━━━━━━━━━━━━━━━━━━━",
            f"📊 전체 open 이슈: {len(open_issues)}건",
            f"🔴 긴급 에스컬레이션: {len(urgent)}건",
            f"🟡 표류 이슈: {len(drifting)}건",
            f"⚪ 무주 이슈: {len(unowned)}건",
            "",
        ]

        # 🔴 긴급 에스컬레이션
        if urgent:
            lines.append("🔴 긴급 에스컬레이션 (초과 + 고우선순위)")
            lines.append("─" * 30)
            for s, issue in urgent[:7]:
                iid = issue.get("issue_id", "?")
                title = issue.get("title", "?")[:35]
                prio = issue.get("priority", "?")
                due = issue.get("due_date", "미지정")
                org = issue.get("source_origin", "")
                lines.append(f"  • {iid}: {title}")
                lines.append(f"    [{prio}] 마감: {due} | 방치점수: {s:.1f}")
                if org:
                    lines.append(f"    → 에스컬레이션 대상: {_normalize_org(org)}")
            lines.append("")

        # 🟡 표류 이슈
        if drifting:
            lines.append("🟡 표류 이슈 (업데이트 없음 / 높은 방치점수)")
            lines.append("─" * 30)
            for s, issue in drifting[:7]:
                iid = issue.get("issue_id", "?")
                title = issue.get("title", "?")[:35]
                prio = issue.get("priority", "?")
                age = _days_since(_parse_created_date(issue))
                lines.append(
                    f"  • {iid}: {title} [{prio}] "
                    f"경과: {age}일 | 점수: {s:.1f}"
                )
            lines.append("")

        # ⚪ 무주 이슈
        if unowned:
            lines.append("⚪ 무주 이슈 (owner 미배정)")
            lines.append("─" * 30)
            for s, issue in unowned[:5]:
                iid = issue.get("issue_id", "?")
                title = issue.get("title", "?")[:35]
                cat = issue.get("category", "?")
                lines.append(f"  • {iid}: {title} [{cat}]")
            lines.append("")

        if not (urgent or drifting or unowned):
            lines.append("✅ 방치 이슈 없음! 모든 이슈가 정상 관리 중입니다.")

        # 요약 권고
        if urgent:
            lines.append("💡 권고: 🔴 긴급 항목부터 협력사 연락 필요")

        return {"result_text": "\n".join(lines), "files": []}

    except Exception as e:
        return {
            "result_text": f"❌ 방치 이슈 탐지 오류: {e}\n{traceback.format_exc()[:500]}",
            "files": [],
        }


# ═══════════════════════════════════════════════════════════════
#  스킬 3: decision_logger — 결정사항 기록
# ═══════════════════════════════════════════════════════════════

def _parse_decision_text(instruction: str) -> Tuple[Optional[str], str, Optional[str]]:
    """
    결정사항 텍스트 파싱.

    지원 형식:
      "SEN-335 결정: HMB 전단보강 추가, 2/16 도면 반영"
      "SEN-335 결정사항 HMB 전단보강 추가"

    Returns:
        (issue_id, decision_text, due_date_str)
    """
    # SEN-ID 추출
    sen_refs = detect_sen_refs(instruction)
    issue_id = sen_refs[0] if sen_refs else None

    # "결정:" 또는 "결정사항" 이후 텍스트 추출
    decision_text = ""
    patterns = [
        r"결정\s*[:：]\s*(.+)",
        r"결정사항\s*[:：]?\s*(.+)",
        r"의사결정\s*[:：]?\s*(.+)",
        r"decision\s*[:：]\s*(.+)",
    ]
    for pat in patterns:
        m = re.search(pat, instruction, re.IGNORECASE)
        if m:
            decision_text = m.group(1).strip()
            break

    if not decision_text and issue_id:
        # SEN-ID 이후 전체를 결정 텍스트로 사용
        idx = instruction.upper().find(issue_id.upper())
        if idx >= 0:
            after = instruction[idx + len(issue_id):].strip()
            # 키워드 제거
            for kw in ["결정기록", "결정사항", "의사결정", "결정등록", "결정"]:
                after = after.replace(kw, "").strip()
            if after:
                decision_text = after

    # 날짜 감지 (M/D 또는 YYYY-MM-DD)
    due_date_str = None
    date_patterns = [
        (r"(\d{4})-(\d{1,2})-(\d{1,2})", lambda m: f"{m.group(1)}-{m.group(2).zfill(2)}-{m.group(3).zfill(2)}"),
        (r"(\d{1,2})/(\d{1,2})", lambda m: f"{datetime.now().year}-{m.group(1).zfill(2)}-{m.group(2).zfill(2)}"),
    ]
    for pat, fmt in date_patterns:
        m = re.search(pat, decision_text)
        if m:
            due_date_str = fmt(m)
            break

    return issue_id, decision_text, due_date_str


def _update_issue_frontmatter(
    filepath: str, updates: Dict[str, Any]
) -> bool:
    """
    이슈 파일의 YAML frontmatter 필드 업데이트.

    안전 조치:
      - 원본 내용 유지, 지정된 필드만 업데이트
      - 파일 읽기 → 수정 → 쓰기 (in-place)
    """
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        if not content.startswith("---"):
            return False

        parts = content.split("---", 2)
        if len(parts) < 3:
            return False

        # YAML 파싱은 하지 않고 텍스트 레벨 교체 (안전)
        fm_text = parts[1]
        for key, value in updates.items():
            # 기존 필드가 있으면 교체
            pattern = rf"^({re.escape(key)}\s*:\s*)(.*)$"
            new_line = f"{key}: {value}"
            if re.search(pattern, fm_text, re.MULTILINE):
                fm_text = re.sub(pattern, new_line, fm_text, flags=re.MULTILINE)
            else:
                # 필드가 없으면 추가
                fm_text = fm_text.rstrip() + f"\n{new_line}\n"

        new_content = f"---{fm_text}---{parts[2]}"
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(new_content)
        return True

    except Exception:
        return False


def run_decision_logger(context: dict) -> dict:
    """
    결정사항 기록.

    메시지에서 SEN-ID + 결정 텍스트 파싱 → 해당 이슈 파일의
    decision 필드 업데이트 + 상태 전환.

    ⚠️ 파일 쓰기 포함 — 변경 전 확인 메시지 제공.
    """
    send_progress = context.get("send_progress", lambda x: None)
    combined = context.get("combined", {})
    instruction = combined.get("combined_instruction", "")

    send_progress("📝 결정사항 파싱 중...")

    try:
        issue_id, decision_text, due_date_str = _parse_decision_text(instruction)

        if not issue_id:
            return {
                "result_text": (
                    "⚠️ 결정을 기록할 이슈 ID를 찾을 수 없습니다.\n\n"
                    "사용법:\n"
                    '• "SEN-335 결정: HMB 전단보강 추가, 2/16 도면 반영"\n'
                    '• "SEN-428 결정사항 PSRC 접합부 재검토"'
                ),
                "files": [],
            }

        if not decision_text:
            return {
                "result_text": (
                    f"⚠️ {issue_id}에 기록할 결정 내용이 비어있습니다.\n\n"
                    "예시: \"SEN-335 결정: 전단보강 추가\""
                ),
                "files": [],
            }

        # 이슈 로드
        issue = get_issue_by_id(issue_id)
        if not issue:
            return {
                "result_text": f"⚠️ {issue_id} 이슈를 찾을 수 없습니다.",
                "files": [],
            }

        filepath = issue.get("_file_path", "")
        if not filepath or not os.path.exists(filepath):
            return {
                "result_text": f"⚠️ {issue_id} 파일 경로를 찾을 수 없습니다.",
                "files": [],
            }

        # 변경 전 상태
        old_decision = issue.get("decision", "(없음)")
        old_status = issue.get("status", "")
        old_due = issue.get("due_date", "(없음)")

        # 업데이트 항목 준비
        updates: Dict[str, Any] = {}
        today_str = datetime.now().strftime("%Y-%m-%d")
        new_decision = f"{decision_text} ({today_str})"

        # 기존 decision이 있으면 누적
        if old_decision and old_decision != "(없음)":
            new_decision = f"{old_decision} | {new_decision}"

        updates["decision"] = f'"{new_decision}"'

        # due_date 업데이트
        if due_date_str:
            updates["due_date"] = due_date_str

        # 상태 전환: open → in_progress
        new_status = old_status
        if old_status.lower() == "open":
            updates["issue_status"] = "in_progress"
            new_status = "in_progress"

        send_progress(f"💾 {issue_id} 업데이트 중...")

        # 파일 업데이트
        success = _update_issue_frontmatter(filepath, updates)

        if not success:
            return {
                "result_text": f"❌ {issue_id} 파일 업데이트 실패.",
                "files": [],
            }

        # 결과 포맷팅
        lines = [
            f"📝 결정사항 기록 완료: {issue_id}",
            "━━━━━━━━━━━━━━━━━━━━━━━━",
            f"📌 이슈: {issue.get('title', '')}",
            "",
            "▸ 변경 내역:",
            f"  📋 결정: {decision_text}",
        ]
        if due_date_str:
            lines.append(f"  📅 마감일: {old_due} → {due_date_str}")
        if new_status != old_status:
            lines.append(f"  🔄 상태: {old_status} → {new_status}")
        lines.append("")
        lines.append(f"  💾 파일: {os.path.basename(filepath)}")

        return {"result_text": "\n".join(lines), "files": []}

    except Exception as e:
        return {
            "result_text": f"❌ 결정 기록 오류: {e}\n{traceback.format_exc()[:500]}",
            "files": [],
        }


# ═══════════════════════════════════════════════════════════════
#  스킬 4: lead_time_tracker — 리드타임 추적
# ═══════════════════════════════════════════════════════════════

def _estimate_remaining_lead_time(
    member_type: str, current_stage: str
) -> int:
    """현재 단계부터 시공 완료까지 잔여 리드타임(일) 추정."""
    lt = _LEAD_TIMES.get(member_type)
    if not lt:
        return 0

    # 현재 단계 인덱스
    cur_idx = _STAGE_IDX.get(current_stage, 0)

    remaining = 0
    for stage in _STAGE_ORDER[cur_idx:]:
        lt_key = _STAGE_LT_KEY.get(stage, "")
        if lt_key in lt:
            remaining += lt[lt_key]
    return remaining


def run_lead_time_tracker(context: dict) -> dict:
    """
    리드타임 추적.

    부재별 제작 관련 이슈를 로드 → 현재 단계 판별 → 잔여 리드타임 산출
    → due_date 대비 갭 분석 → 지연 위험 표시.
    """
    send_progress = context.get("send_progress", lambda x: None)
    combined = context.get("combined", {})
    instruction = combined.get("combined_instruction", "")

    send_progress("⏱️ 리드타임 분석 중...")

    try:
        all_issues = _get_open_issues()
        if not all_issues:
            return {"result_text": "⚠️ 분석할 이슈가 없습니다.", "files": []}

        # 제작 관련 이슈 필터
        fab_issues = [
            i for i in all_issues
            if (i.get("category") or "").lower() in FABRICATION_CATEGORIES
        ]

        if not fab_issues:
            return {
                "result_text": "ℹ️ 제작 관련 이슈가 없습니다.",
                "files": [],
            }

        # 부재 타입별 분류
        type_groups: Dict[str, List[Dict]] = {}
        for issue in fab_issues:
            mt = _detect_member_type(issue) or "기타"
            type_groups.setdefault(mt, []).append(issue)

        lines = [
            "⏱️ 리드타임 추적 분석",
            "━━━━━━━━━━━━━━━━━━━━━━━━",
            f"📊 제작 관련 이슈: {len(fab_issues)}건",
            "",
        ]

        risk_summary = {"red": 0, "yellow": 0, "green": 0}

        for member_type in ["psrc", "hmb", "pc", "ep", "기타"]:
            issues = type_groups.get(member_type, [])
            if not issues:
                continue

            lt_info = _LEAD_TIMES.get(member_type)
            total_lt = sum(lt_info.values()) if lt_info else 0
            lines.append(f"▸ {member_type.upper()} ({len(issues)}건) — 총 리드타임: {total_lt}일")
            lines.append("─" * 30)

            # 단계별 분류
            stages = classify_stages(issues)
            for stage_name in _STAGE_ORDER + ["미분류"]:
                stage_issues = stages.get(stage_name, [])
                if not stage_issues:
                    continue

                icon = get_stage_icon(stage_name)
                lines.append(f"  {icon} {stage_name}: {len(stage_issues)}건")

                for si in stage_issues[:3]:
                    iid = si.get("issue_id", "?")
                    title = si.get("title", "?")[:25]
                    due = _parse_due_date(si)

                    # 잔여 리드타임 계산
                    remaining = _estimate_remaining_lead_time(member_type, stage_name)

                    if due:
                        gap = (due - datetime.now()).days - remaining
                        if gap < 0:
                            risk = "🔴"
                            risk_summary["red"] += 1
                        elif gap < 7:
                            risk = "🟡"
                            risk_summary["yellow"] += 1
                        else:
                            risk = "🟢"
                            risk_summary["green"] += 1
                        lines.append(
                            f"    {risk} {iid}: {title} "
                            f"(잔여LT: {remaining}일, 갭: {gap:+d}일)"
                        )
                    else:
                        lines.append(
                            f"    ⚪ {iid}: {title} "
                            f"(잔여LT: {remaining}일, 마감: 미지정)"
                        )

                if len(stage_issues) > 3:
                    lines.append(f"    ... 외 {len(stage_issues) - 3}건")
            lines.append("")

        # 리스크 요약
        lines.append("▸ 리스크 요약:")
        lines.append(
            f"  🔴 지연위험: {risk_summary['red']}건 | "
            f"🟡 주의: {risk_summary['yellow']}건 | "
            f"🟢 정상: {risk_summary['green']}건"
        )

        if risk_summary["red"] > 0:
            lines.append("")
            lines.append("💡 🔴 항목은 리드타임 내 완료 불가능 — 공정 재조정 필요")

        return {"result_text": "\n".join(lines), "files": []}

    except Exception as e:
        return {
            "result_text": f"❌ 리드타임 분석 오류: {e}\n{traceback.format_exc()[:500]}",
            "files": [],
        }


# ═══════════════════════════════════════════════════════════════
#  스킬 5: contractor_digest — 협력사별 현황
# ═══════════════════════════════════════════════════════════════

def _group_by_contractor(issues: List[Dict]) -> Dict[str, List[Dict]]:
    """이슈를 source_origin별로 그룹핑."""
    groups: Dict[str, List[Dict]] = {}
    for issue in issues:
        org = (issue.get("source_origin") or "미지정").strip()
        if org:
            org = _normalize_org(org)
        else:
            org = "미지정"
        groups.setdefault(org, []).append(issue)
    return groups


def run_contractor_digest(context: dict) -> dict:
    """
    협력사별 현황 스코어카드.

    전체 open 이슈를 source_origin별 그룹핑 →
    이슈 수, 우선순위 분포, 초과 건수, Top 3 긴급 항목 출력.

    특정 업체명 언급 시 상세 모드로 전환.
    """
    send_progress = context.get("send_progress", lambda x: None)
    combined = context.get("combined", {})
    instruction = combined.get("combined_instruction", "")

    send_progress("🏢 협력사별 현황 분석 중...")

    try:
        open_issues = _get_open_issues()
        if not open_issues:
            return {"result_text": "⚠️ 열린 이슈가 없습니다.", "files": []}

        groups = _group_by_contractor(open_issues)

        # 특정 업체 상세 모드 감지
        target_org = None
        inst_lower = instruction.lower()
        for key, canonical in _ORG_NAMES.items():
            if key in inst_lower:
                target_org = canonical
                break

        lines = [
            "🏢 협력사별 현황 스코어카드",
            "━━━━━━━━━━━━━━━━━━━━━━━━",
            f"📊 전체 open 이슈: {len(open_issues)}건 | 협력사: {len(groups)}개",
            "",
        ]

        if target_org and target_org in groups:
            # ─── 상세 모드 ───
            org_issues = groups[target_org]
            lines.append(f"▸ {target_org} 상세 현황 ({len(org_issues)}건)")
            lines.append("─" * 30)

            # 우선순위 분포
            prio_dist: Dict[str, int] = {}
            overdue_count = 0
            no_decision = 0
            for i in org_issues:
                p = (i.get("priority") or "medium").lower()
                prio_dist[p] = prio_dist.get(p, 0) + 1
                due = _parse_due_date(i)
                if due and datetime.now() > due:
                    overdue_count += 1
                if not i.get("decision", "").strip():
                    no_decision += 1

            prio_str = " | ".join(
                f"{p}: {c}" for p, c in sorted(prio_dist.items())
            )
            lines.append(f"  우선순위: {prio_str}")
            lines.append(f"  초과: {overdue_count}건 | 미결정: {no_decision}건")
            lines.append(f"  평균 연령: {sum(_days_since(_parse_created_date(i)) for i in org_issues) // max(len(org_issues), 1)}일")
            lines.append("")

            # 전체 이슈 목록
            lines.append("  📋 전체 이슈:")
            for i in sorted(
                org_issues,
                key=lambda x: PRIORITY_URGENCY.get(
                    (x.get("priority") or "medium").lower(), 0.5
                ),
                reverse=True,
            ):
                iid = i.get("issue_id", "?")
                title = i.get("title", "?")[:30]
                prio = i.get("priority", "?")
                status = i.get("status", "?")
                lines.append(f"    • {iid}: {title} [{prio}/{status}]")
        else:
            # ─── 개요 모드 ───
            for org_name in sorted(
                groups.keys(),
                key=lambda o: len(groups[o]),
                reverse=True,
            ):
                org_issues = groups[org_name]
                overdue = sum(
                    1 for i in org_issues
                    if _parse_due_date(i) and datetime.now() > _parse_due_date(i)
                )
                no_decision = sum(
                    1 for i in org_issues
                    if not i.get("decision", "").strip()
                )

                # 우선순위별 카운트
                crit_high = sum(
                    1 for i in org_issues
                    if (i.get("priority") or "").lower() in ("critical", "high")
                )

                avg_age = sum(
                    _days_since(_parse_created_date(i)) for i in org_issues
                ) // max(len(org_issues), 1)

                lines.append(
                    f"▸ {org_name}: {len(org_issues)}건 "
                    f"(긴급: {crit_high}, 초과: {overdue}, 미결정: {no_decision}, "
                    f"평균 {avg_age}일)"
                )

                # Top 3 긴급
                urgent = sorted(
                    org_issues,
                    key=lambda x: PRIORITY_URGENCY.get(
                        (x.get("priority") or "medium").lower(), 0.5
                    ),
                    reverse=True,
                )
                for i in urgent[:3]:
                    iid = i.get("issue_id", "?")
                    title = i.get("title", "?")[:25]
                    prio = i.get("priority", "?")
                    lines.append(f"    • {iid}: {title} [{prio}]")
                lines.append("")

        lines.append("💡 특정 업체 상세: \"삼성현황\", \"센구조현황\" 등으로 조회 가능")

        return {"result_text": "\n".join(lines), "files": []}

    except Exception as e:
        return {
            "result_text": f"❌ 협력사 현황 오류: {e}\n{traceback.format_exc()[:500]}",
            "files": [],
        }


# ═══════════════════════════════════════════════════════════════
#  스킬 6: weekly_executive — 주간 경영보고
# ═══════════════════════════════════════════════════════════════

def run_weekly_executive(context: dict) -> dict:
    """
    주간 경영보고 통합.

    4개 데이터 소스 통합:
      1. 이슈 DB → 대시보드 (총/신규/해결/초과/방치)
      2. 리스크 매트릭스 → 상위 5건 Q1
      3. 제작 파이프라인 → 부재별 단계 현황
      4. 협력사 → 스코어카드 요약
    Excel 4시트 출력.
    """
    send_progress = context.get("send_progress", lambda x: None)
    combined = context.get("combined", {})
    instruction = combined.get("combined_instruction", "")

    send_progress("📊 주간 경영보고 생성 중...")

    try:
        all_issues = load_vault_issues()
        open_issues = [
            i for i in all_issues
            if i.get("status", "").lower() not in ("closed", "resolved")
        ]

        today = datetime.now()
        week_ago = today - timedelta(days=7)

        # ── Sheet 1 데이터: 경영 요약 KPI ──
        total = len(all_issues)
        total_open = len(open_issues)
        new_7d = sum(
            1 for i in all_issues
            if _parse_created_date(i) and _parse_created_date(i) >= week_ago
        )
        resolved_7d = sum(
            1 for i in all_issues
            if i.get("status", "").lower() in ("closed", "resolved")
            and _parse_created_date(i) and _parse_created_date(i) >= week_ago
        )
        overdue = sum(
            1 for i in open_issues
            if _parse_due_date(i) and today > _parse_due_date(i)
        )

        # 방치 이슈 수
        stale_count = sum(
            1 for i in open_issues
            if _calculate_staleness(i) >= 3.0
        )

        kpi_header = ["KPI", "값", "신호등"]
        kpi_data = [
            ["전체 이슈", str(total), ""],
            ["Open 이슈", str(total_open), "🟡" if total_open > 30 else "🟢"],
            ["금주 신규", str(new_7d), ""],
            ["금주 해결", str(resolved_7d), "🟢" if resolved_7d >= new_7d else "🟡"],
            ["마감 초과", str(overdue), "🔴" if overdue > 5 else "🟡" if overdue > 0 else "🟢"],
            ["방치 이슈", str(stale_count), "🔴" if stale_count > 3 else "🟡" if stale_count > 0 else "🟢"],
        ]

        # ── Sheet 2 데이터: 이슈 상세 ──
        detail_header = [
            "이슈ID", "제목", "카테고리", "우선순위", "상태",
            "담당자", "마감일", "zone", "source_origin",
        ]
        detail_data = []
        for i in sorted(
            open_issues,
            key=lambda x: PRIORITY_URGENCY.get(
                (x.get("priority") or "medium").lower(), 0.5
            ),
            reverse=True,
        ):
            detail_data.append([
                i.get("issue_id", ""),
                i.get("title", "")[:50],
                i.get("category", ""),
                i.get("priority", ""),
                i.get("status", ""),
                i.get("owner", ""),
                str(i.get("due_date", "")),
                i.get("zone", ""),
                i.get("source_origin", ""),
            ])

        # ── Sheet 3 데이터: 리스크 매트릭스 ──
        risk_header = ["이슈ID", "제목", "리스크점수", "카테고리", "우선순위"]
        risk_data = []
        for i in open_issues:
            cat = (i.get("category") or "").lower()
            prio = (i.get("priority") or "medium").lower()
            cat_w = CATEGORY_IMPACT.get(cat, 0.5)
            prio_w = PRIORITY_URGENCY.get(prio, 0.5)
            rscore = round(cat_w * prio_w * 10, 1)
            risk_data.append([
                i.get("issue_id", ""),
                i.get("title", "")[:40],
                rscore,
                i.get("category", ""),
                i.get("priority", ""),
            ])
        risk_data.sort(key=lambda x: x[2], reverse=True)

        # ── Sheet 4 데이터: 제작 파이프라인 ──
        fab_issues = [
            i for i in open_issues
            if (i.get("category") or "").lower() in FABRICATION_CATEGORIES
        ]
        pipe_header = ["부재타입", "단계", "이슈수"]
        pipe_data = []
        type_groups: Dict[str, List[Dict]] = {}
        for i in fab_issues:
            mt = _detect_member_type(i) or "기타"
            type_groups.setdefault(mt, []).append(i)

        for mt in ["psrc", "hmb", "pc", "ep", "기타"]:
            issues = type_groups.get(mt, [])
            if not issues:
                continue
            stages = classify_stages(issues)
            for stage_name in _STAGE_ORDER + ["미분류"]:
                si = stages.get(stage_name, [])
                if si:
                    pipe_data.append([mt.upper(), stage_name, len(si)])

        # Excel 생성
        send_progress("📝 Excel 파일 생성 중...")

        # 작업 폴더 결정
        task_dir = context.get("task_dir", os.getcwd())
        today_str = today.strftime("%Y%m%d")
        output_path = os.path.join(task_dir, f"P5_주간경영보고_{today_str}.xlsx")

        sheets = {
            "경영 요약": (kpi_header, kpi_data),
            "이슈 상세": (detail_header, detail_data),
            "리스크 매트릭스": (risk_header, risk_data),
            "제작 파이프라인": (pipe_header, pipe_data),
        }

        result_path = create_excel_workbook(sheets, output_path)

        # 텍스트 요약도 생성
        lines = [
            "📊 주간 경영보고 생성 완료",
            "━━━━━━━━━━━━━━━━━━━━━━━━",
            f"📅 기준일: {today.strftime('%Y-%m-%d')}",
            "",
            "▸ KPI 요약:",
            f"  📌 전체: {total}건 | Open: {total_open}건",
            f"  🆕 금주 신규: {new_7d}건 | ✅ 금주 해결: {resolved_7d}건",
            f"  ⏰ 마감 초과: {overdue}건 | 🔎 방치: {stale_count}건",
            "",
            "▸ 리스크 Top 5:",
        ]
        for rd in risk_data[:5]:
            lines.append(f"  • {rd[0]}: {rd[1]} (점수: {rd[2]})")

        lines.append("")
        lines.append("▸ 제작 파이프라인:")
        for pd_row in pipe_data:
            lines.append(f"  • {pd_row[0]} {pd_row[1]}: {pd_row[2]}건")

        files = [result_path] if result_path else []
        if result_path:
            lines.append("")
            lines.append(f"📎 Excel: {os.path.basename(result_path)}")

        return {"result_text": "\n".join(lines), "files": files}

    except Exception as e:
        return {
            "result_text": f"❌ 주간보고 생성 오류: {e}\n{traceback.format_exc()[:500]}",
            "files": [],
        }


# ═══════════════════════════════════════════════════════════════
#  스킬 7: spec_checker — 사양 검증
# ═══════════════════════════════════════════════════════════════

def _extract_specs_from_text(text: str) -> Dict[str, List[str]]:
    """
    OCR 텍스트에서 구조 사양 추출.

    추출 항목:
      - dimensions: 부재 치수 (H-400×200, □-300×300 등)
      - rebar: 철근 사양 (D22@200, HD25 등)
      - concrete: 콘크리트 강도 (fck 40MPa)
      - steel_grade: 강종 (SM490, SS400)
      - drawing_no: 도면번호
    """
    specs: Dict[str, List[str]] = {
        "dimensions": [],
        "rebar": [],
        "concrete": [],
        "steel_grade": [],
        "drawing_no": [],
    }

    if not text:
        return specs

    # 부재 치수: H-400×200, □-300×300, Ø-400 등
    dim_patterns = [
        r"[HhI]-?\d+[×xX]\d+(?:[×xX]\d+(?:[×xX]\d+)?)?",
        r"□-?\d+[×xX]\d+",
        r"[Øø]-?\d+",
        r"\d+[×xX]\d+[×xX]\d+",
    ]
    for pat in dim_patterns:
        specs["dimensions"].extend(re.findall(pat, text))

    # 철근 사양: D22@200, HD25, D13-CTC200
    rebar_patterns = [
        r"H?D\d+@\d+",
        r"H?D\d+-?CTC\d+",
        r"HD\d+",
        r"D\d+",
    ]
    for pat in rebar_patterns:
        specs["rebar"].extend(re.findall(pat, text))

    # 콘크리트 강도: fck=40, fck 40MPa, 40MPa
    concrete_patterns = [
        r"[Ff][Cc][Kk]\s*[=]?\s*\d+\s*MPa?",
        r"\d+\s*MPa",
    ]
    for pat in concrete_patterns:
        specs["concrete"].extend(re.findall(pat, text))

    # 강종: SM490, SS400, SN490, SHN490
    steel_patterns = [
        r"S[SMNHR]{1,3}\d{3}[A-Z]?",
    ]
    for pat in steel_patterns:
        specs["steel_grade"].extend(re.findall(pat, text))

    # 도면번호: S-XXX, ST-XXX 패턴
    dwg_patterns = [
        r"S[T]?-\d{3,4}[A-Z]?",
        r"[A-Z]{2,3}-\d{3,4}",
    ]
    for pat in dwg_patterns:
        specs["drawing_no"].extend(re.findall(pat, text))

    # 중복 제거
    for key in specs:
        specs[key] = list(dict.fromkeys(specs[key]))

    return specs


def _cross_check_specs(
    ocr_specs: Dict[str, List[str]],
    issue_constraints: List[Dict],
) -> List[Dict[str, str]]:
    """
    OCR 추출 사양과 이슈 제약조건 교차검증.

    Returns:
        [{check_item, ocr_value, constraint, result, issue_ref}]
    """
    results: List[Dict[str, str]] = []

    for issue in issue_constraints:
        iid = issue.get("issue_id", "")
        body = f"{issue.get('_body', '')} {issue.get('action_plan', '')}".upper()
        title = issue.get("title", "")

        # 강종 검증
        for grade in ocr_specs.get("steel_grade", []):
            if grade.upper() in body:
                results.append({
                    "check_item": "강종",
                    "ocr_value": grade,
                    "constraint": f"이슈 내 일치",
                    "result": "PASS",
                    "issue_ref": f"{iid}: {title[:30]}",
                })
            else:
                # 다른 강종이 이슈에 언급되어 있으면 WARN
                issue_grades = re.findall(r"S[SMNHR]{1,3}\d{3}[A-Z]?", body)
                if issue_grades:
                    results.append({
                        "check_item": "강종",
                        "ocr_value": grade,
                        "constraint": f"이슈 강종: {', '.join(issue_grades[:3])}",
                        "result": "WARN",
                        "issue_ref": f"{iid}: {title[:30]}",
                    })

        # 치수 검증 — 이슈 body에 동일 치수 언급 확인
        for dim in ocr_specs.get("dimensions", []):
            dim_upper = dim.upper().replace("×", "X")
            body_normalized = body.replace("×", "X")
            if dim_upper in body_normalized:
                results.append({
                    "check_item": "부재 치수",
                    "ocr_value": dim,
                    "constraint": "이슈 내 일치",
                    "result": "PASS",
                    "issue_ref": f"{iid}: {title[:30]}",
                })

        # 콘크리트 강도 검증
        for conc in ocr_specs.get("concrete", []):
            mpa = re.search(r"\d+", conc)
            if mpa:
                mpa_val = mpa.group()
                if mpa_val in body and "MPA" in body:
                    results.append({
                        "check_item": "콘크리트 강도",
                        "ocr_value": conc,
                        "constraint": "이슈 내 일치",
                        "result": "PASS",
                        "issue_ref": f"{iid}: {title[:30]}",
                    })

    return results


def run_spec_checker(context: dict) -> dict:
    """
    사양 검증.

    첨부된 Shop DWG (PDF/이미지) → OCR 파이프라인 → 사양 추출
    → 이슈DB 교차검증 → PASS/WARN/FAIL 판정.

    ⚠️ 파일 첨부 필수 (requires_file=True).
    """
    send_progress = context.get("send_progress", lambda x: None)
    combined = context.get("combined", {})
    instruction = combined.get("combined_instruction", "")
    task_dir = context.get("task_dir", os.getcwd())

    send_progress("🔍 사양 검증 시작...")

    try:
        # 1. 도면 분석 실행 (기존 파이프라인 활용)
        from scripts.telegram.skills.analysis_skills import run_drawing_analyze

        send_progress("📐 도면 OCR 분석 중...")
        drawing_result = run_drawing_analyze(context)
        drawing_text = drawing_result.get("result_text", "")

        if "분석할 도면 파일" in drawing_text or "파일을 첨부" in drawing_text:
            return {
                "result_text": (
                    "⚠️ 사양 검증을 위한 도면 파일이 없습니다.\n\n"
                    "사용법:\n"
                    "1. Shop DWG (PDF/이미지)를 첨부하고\n"
                    '2. "사양검증" 또는 "스펙체크" 메시지 전송\n\n'
                    "지원 형식: PDF, PNG, JPG, DXF"
                ),
                "files": [],
            }

        # 2. OCR 결과에서 사양 추출
        send_progress("🔎 사양 정보 추출 중...")
        ocr_specs = _extract_specs_from_text(drawing_text)

        # 어떤 사양이 추출되었는지 확인
        total_specs = sum(len(v) for v in ocr_specs.values())
        if total_specs == 0:
            lines = [
                "⚠️ 도면에서 구조 사양을 추출할 수 없습니다.",
                "",
                "도면 분석 결과:",
                drawing_text[:500],
            ]
            return {
                "result_text": "\n".join(lines),
                "files": drawing_result.get("files", []),
            }

        # 3. 관련 이슈 검색
        send_progress("📋 이슈DB 교차검증 중...")

        # SEN-ID, 도면번호로 관련 이슈 검색
        sen_refs = detect_sen_refs(drawing_text + " " + instruction)
        dwg_refs = detect_drawing_refs(drawing_text + " " + instruction)

        related_issues: List[Dict] = []
        for ref in sen_refs[:10]:
            issue = get_issue_by_id(ref)
            if issue:
                related_issues.append(issue)

        # 도면번호로도 검색
        for dwg_ref in dwg_refs[:5]:
            hits = search_issues(dwg_ref, max_results=3)
            for h in hits:
                if h.get("issue_id") not in [
                    i.get("issue_id") for i in related_issues
                ]:
                    related_issues.append(h)

        # 이슈 없으면 카테고리 기반 검색 시도
        if not related_issues:
            # 부재 타입 감지 후 관련 이슈 로드
            for dim in ocr_specs.get("dimensions", [])[:1]:
                hits = search_issues(dim, max_results=5)
                related_issues.extend(hits)

        # 4. 교차검증 실행
        check_results = _cross_check_specs(ocr_specs, related_issues)

        # 5. 결과 포맷팅
        lines = [
            "🔍 사양 검증 결과",
            "━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
            "▸ 추출된 사양:",
        ]

        spec_labels = {
            "dimensions": "📏 부재 치수",
            "rebar": "🔩 철근 사양",
            "concrete": "🧱 콘크리트",
            "steel_grade": "🔧 강종",
            "drawing_no": "📄 도면번호",
        }
        for key, label in spec_labels.items():
            values = ocr_specs.get(key, [])
            if values:
                lines.append(f"  {label}: {', '.join(values[:5])}")

        lines.append(f"\n📋 관련 이슈: {len(related_issues)}건")

        if check_results:
            lines.append("")
            lines.append("▸ 교차검증 결과:")
            lines.append("─" * 30)

            pass_count = sum(1 for r in check_results if r["result"] == "PASS")
            warn_count = sum(1 for r in check_results if r["result"] == "WARN")
            fail_count = sum(1 for r in check_results if r["result"] == "FAIL")

            for r in check_results:
                icon = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}.get(
                    r["result"], "?"
                )
                lines.append(
                    f"  {icon} {r['check_item']}: {r['ocr_value']} "
                    f"→ {r['result']}"
                )
                lines.append(f"     근거: {r['issue_ref']}")
                if r["result"] != "PASS":
                    lines.append(f"     제약: {r['constraint']}")

            lines.append("")
            lines.append(
                f"📊 요약: ✅ PASS {pass_count} | "
                f"⚠️ WARN {warn_count} | "
                f"❌ FAIL {fail_count}"
            )
        else:
            lines.append("")
            lines.append(
                "ℹ️ 이슈DB에서 일치하는 사양 제약조건을 찾지 못했습니다."
            )
            lines.append("   수동 확인이 필요합니다.")

        return {
            "result_text": "\n".join(lines),
            "files": drawing_result.get("files", []),
        }

    except Exception as e:
        return {
            "result_text": f"❌ 사양 검증 오류: {e}\n{traceback.format_exc()[:500]}",
            "files": [],
        }
