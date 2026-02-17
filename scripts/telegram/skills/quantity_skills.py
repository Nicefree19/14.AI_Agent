#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
골조 물량 분석 스킬

P5 복합동 선제작(RISK 발주) 관련 골조 물량 데이터 조회/분석/비교.
데이터 출처: ResearchVault/_config/p5-quantity-data.yaml
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


# ─── 데이터 로드 ────────────────────────────────────────

_DATA_PATH = Path(__file__).resolve().parents[3] / "ResearchVault" / "_config" / "p5-quantity-data.yaml"
_cache: Optional[Dict[str, Any]] = None


def _load_data() -> Dict[str, Any]:
    """YAML 데이터 로드 (캐시)."""
    global _cache
    if _cache is not None:
        return _cache
    if not _DATA_PATH.exists():
        return {}
    with open(_DATA_PATH, "r", encoding="utf-8") as f:
        _cache = yaml.safe_load(f) or {}
    return _cache


def reload_data():
    """캐시 무효화 후 재로드."""
    global _cache
    _cache = None
    return _load_data()


# ─── 핵심 조회 함수 ─────────────────────────────────────

def get_case_summary(case_id: Optional[str] = None) -> str:
    """CASE별 물량 증가분 요약."""
    data = _load_data()
    cases = data.get("cases", {})

    if case_id and case_id in cases:
        return _format_case(case_id, cases[case_id])

    lines = [
        "📊 P5 복합동 선제작(RISK 발주) 물량 비교",
        "━" * 35,
        "",
    ]
    for cid, c in cases.items():
        lines.append(_format_case(cid, c))
        lines.append("")
    return "\n".join(lines)


def _format_case(case_id: str, case: dict) -> str:
    """단일 CASE 포맷."""
    label = case_id.upper().replace("_", " ")
    lines = [
        f"▶ {label}: {case.get('description', '')}",
        f"  적용 층: {case.get('floor_range', '-')}",
    ]
    for key, qty in case.get("quantities", {}).items():
        name = qty.get("note", key)
        if "increase_m3" in qty:
            lines.append(f"  • {name}: +{qty['increase_m3']:,} m³ ({qty.get('increase_pct', '?')}%)")
        elif "increase_ton" in qty:
            lines.append(f"  • {name}: +{qty['increase_ton']:,} ton ({qty.get('increase_pct', '?')}%)")
        elif "increase_pct_max" in qty:
            lines.append(f"  • {name}: 최대 +{qty['increase_pct_max']}%")
    src = case.get("source_issue") or case.get("source_issues", [])
    if isinstance(src, list):
        lines.append(f"  출처: {', '.join(src)}")
    else:
        lines.append(f"  출처: {src}")
    return "\n".join(lines)


def get_component_detail(component: Optional[str] = None) -> str:
    """부재별 물량 상세."""
    data = _load_data()
    components = data.get("components", {})

    if component:
        # 부재명 매칭 (부분 매칭)
        key = _find_component_key(component, components)
        if key:
            return _format_component(key, components[key])
        return f"❌ '{component}' 부재를 찾을 수 없습니다. 가능한 부재: {', '.join(c.get('name', k) for k, c in components.items())}"

    lines = [
        "🏗️ P5 복합동 부재별 물량 영향",
        "━" * 35,
        "",
    ]
    for key, comp in components.items():
        lines.append(_format_component(key, comp))
        lines.append("")
    return "\n".join(lines)


def _format_component(key: str, comp: dict) -> str:
    """단일 부재 포맷."""
    lines = [
        f"▶ {comp.get('name', key)} ({comp.get('description', '')})",
    ]
    impact = comp.get("risk_impact", {})
    for k, v in impact.items():
        if k == "note":
            lines.append(f"  ℹ️ {v}")
        elif k == "review_required":
            continue
        elif "pct" in k and "max" in k:
            lines.append(f"  • 최대 증가율: +{v}%")
        elif "pct" in k:
            lines.append(f"  • 증가율: +{v}%")
        elif "ton" in k:
            lines.append(f"  • 증가량: +{v:,} ton")
        elif "m3" in k:
            lines.append(f"  • 증가량: +{v:,} m³")
        elif k == "affected_zones":
            lines.append(f"  • 영향 구역: {v}")
    action = comp.get("action_required", "")
    if action:
        lines.append(f"  ⚠️ 조치: {action}")
    return "\n".join(lines)


def _find_component_key(query: str, components: dict) -> Optional[str]:
    """쿼리 문자열로 부재 키 찾기."""
    q = query.lower().strip()
    aliases = {
        "psrc": "psrc", "피에스알씨": "psrc", "기둥": "psrc",
        "hmb": "hmb", "브라켓": "hmb", "에이치엠비": "hmb",
        "거더": "pc_girder", "보": "pc_girder", "빔": "pc_girder",
        "pc": "pc_total", "피씨": "pc_total", "프리캐스트": "pc_total",
        "현장타설": "cast_in_place", "현타": "cast_in_place", "콘크리트": "cast_in_place",
    }
    if q in aliases:
        return aliases[q]
    for key, comp in components.items():
        name = comp.get("name", "").lower()
        if q in name or q in key:
            return key
    return None


def get_change_summary() -> str:
    """변경점 및 리스크 요약."""
    data = _load_data()
    cs = data.get("change_summary", {})

    lines = [
        "📋 P5 복합동 물량 변경점 요약",
        "━" * 35,
        "",
        f"▶ 배경: {cs.get('trigger', '-')}",
        f"▶ 결정 상태: {cs.get('decision_status', '-')}",
        "",
        "🔄 주요 변경사항:",
    ]
    for c in cs.get("key_changes", []):
        lines.append(f"  • {c}")

    lines.append("")
    lines.append("⚠️ 리스크:")
    for r in cs.get("risks", []):
        lines.append(f"  • {r}")

    lines.append("")
    lines.append("📌 미결 조치사항:")
    for a in cs.get("pending_actions", []):
        lines.append(f"  • {a}")

    return "\n".join(lines)


def get_issue_detail(issue_id: Optional[str] = None) -> str:
    """관련 이슈 상세."""
    data = _load_data()
    issues = data.get("issues", {})

    if issue_id:
        issue_id = issue_id.upper().replace(" ", "")
        if issue_id in issues:
            return _format_issue(issue_id, issues[issue_id])
        return f"❌ '{issue_id}' 이슈를 찾을 수 없습니다."

    lines = [
        "📑 선제작 RISK 발주 관련 이슈 목록",
        "━" * 35,
        "",
    ]
    for iid, issue in issues.items():
        lines.append(_format_issue(iid, issue))
        lines.append("")
    return "\n".join(lines)


def _format_issue(issue_id: str, issue: dict) -> str:
    """단일 이슈 포맷."""
    return "\n".join([
        f"▶ {issue_id}: {issue.get('title', '')[:60]}",
        f"  구역: {issue.get('zone', '-')} | 출처: {issue.get('source', '-')}",
        f"  핵심: {issue.get('key_point', '-')}",
        f"  조치: {issue.get('action', '-')}",
        f"  생성일: {issue.get('created', '-')}",
    ])


# ─── 메인 스킬 함수 (텔레그램 연동) ────────────────────

def run_quantity_analysis(instruction: str, chat_id: str = "", **kwargs) -> Dict[str, Any]:
    """
    물량 분석 스킬 진입점.

    키워드에 따라 적절한 분석 결과를 반환.
    """
    text = instruction.lower()

    # 특정 부재 조회
    component_keywords = {
        "psrc": "psrc", "피에스알씨": "psrc", "철골": "psrc",
        "hmb": "hmb", "브라켓": "hmb",
        "거더": "pc_girder", "보거더": "pc_girder", "빔": "pc_girder",
        "현장타설": "cast_in_place", "현타": "cast_in_place",
        "pc": "pc_total", "피씨": "pc_total",
    }

    for kw, comp_key in component_keywords.items():
        if kw in text:
            result = get_component_detail(comp_key)
            return {"text": result, "files": []}

    # CASE 비교
    if "case" in text or "케이스" in text or "비교" in text:
        result = get_case_summary()
        return {"text": result, "files": []}

    # 변경점/리스크
    if any(kw in text for kw in ["변경", "리스크", "위험", "변경점", "특이사항", "리스크발주"]):
        result = get_change_summary()
        return {"text": result, "files": []}

    # 이슈 조회
    sen_match = re.search(r"SEN-(\d+)", text, re.IGNORECASE)
    if sen_match:
        result = get_issue_detail(f"SEN-{sen_match.group(1)}")
        return {"text": result, "files": []}

    if any(kw in text for kw in ["이슈", "관련이슈"]):
        result = get_issue_detail()
        return {"text": result, "files": []}

    # 기본: 전체 요약
    sections = [
        get_case_summary(),
        "",
        get_change_summary(),
    ]
    return {"text": "\n".join(sections), "files": []}
