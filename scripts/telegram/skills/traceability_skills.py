#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
이슈-도면-제작 연계 추적 스킬 모듈

스킬:
  - run_traceability_map: 이슈↔도면↔제작 크로스-레퍼런스 맵 생성
"""

from __future__ import annotations

import os
import re
import traceback
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

import yaml

from scripts.telegram.skill_utils import (
    ISSUES_DIR,
    DRAWING_PATTERNS,
    SEN_PATTERN,
    detect_sen_refs,
    detect_drawing_refs,
)


def _parse_frontmatter(filepath: Path) -> dict:
    """마크다운 파일에서 YAML frontmatter 파싱."""
    try:
        text = filepath.read_text(encoding="utf-8")
        if not text.startswith("---"):
            return {}
        parts = text.split("---", 2)
        if len(parts) < 3:
            return {}
        fm = yaml.safe_load(parts[1]) or {}
        fm["_body"] = parts[2]
        fm["_filename"] = filepath.name
        return fm
    except Exception:
        return {}


def _extract_refs_from_body(body: str) -> Tuple[List[str], List[str]]:
    """본문에서 SEN 이슈 참조와 도면번호 추출."""
    sen_refs = list(set(re.findall(r"SEN[-_]\d{3,}", body, re.IGNORECASE)))
    drawing_refs = []
    for pat in DRAWING_PATTERNS:
        drawing_refs.extend(pat.findall(body))
    return sen_refs, list(set(drawing_refs))


def _classify_issue_stage(fm: dict) -> str:
    """이슈의 단계 분류 (이슈/도면/제작)."""
    cat = (fm.get("category") or "").lower()
    tags = [str(t).lower() for t in (fm.get("tags") or [])]
    body = (fm.get("_body") or "").lower()

    # 제작 관련
    fab_keywords = ["제작", "fabrication", "shop", "납품", "공장", "용접", "가공"]
    if any(kw in cat for kw in fab_keywords) or any(kw in body[:500] for kw in fab_keywords):
        return "제작"

    # 도면 관련
    dwg_keywords = ["도면", "drawing", "dwg", "출도", "설계", "shop dwg", "afc"]
    if any(kw in cat for kw in dwg_keywords) or any(kw in body[:500] for kw in dwg_keywords):
        return "도면"

    return "이슈"


def run_traceability_map(context: dict) -> dict:
    """이슈-도면-제작 연계 추적 맵 생성.

    1. 모든 이슈 파싱
    2. 이슈 간 SEN 참조/도면번호 참조 추출
    3. 연계 맵 구성 (이슈→도면→제작 흐름)
    4. 고아 이슈(연계 없는 이슈) 식별
    """
    send_progress = context.get("send_progress", lambda x: None)
    task_dir = context.get("task_dir", "")

    send_progress("🔗 이슈 파일 스캔 중...")

    if not ISSUES_DIR.exists():
        return {
            "result_text": "⚠️ 이슈 디렉토리를 찾을 수 없습니다.",
            "files": [],
        }

    # 모든 이슈 파싱
    issues: Dict[str, dict] = {}  # SEN-xxx → frontmatter+body
    md_files = list(ISSUES_DIR.glob("*.md"))

    for fp in md_files:
        fm = _parse_frontmatter(fp)
        if not fm:
            continue
        # SEN ID 추출
        issue_id = fm.get("id") or fm.get("issue_id")
        if not issue_id:
            # 파일명에서 추출 시도
            match = SEN_PATTERN.search(fp.stem)
            if match:
                issue_id = match.group(1)
        if issue_id:
            issue_id = issue_id.upper().replace("_", "-")
            fm["_id"] = issue_id
            issues[issue_id] = fm

    if not issues:
        return {"result_text": "⚠️ 파싱 가능한 이슈가 없습니다.", "files": []}

    send_progress(f"🔗 이슈 {len(issues)}건 연계 분석 중...")

    # 단계별 분류
    stage_map: Dict[str, List[str]] = defaultdict(list)  # stage → [issue_ids]
    for issue_id, fm in issues.items():
        stage = _classify_issue_stage(fm)
        stage_map[stage].append(issue_id)

    # 연계 맵 구성
    # issue_id → {sen_refs: [...], drawing_refs: [...]}
    ref_map: Dict[str, Dict[str, List[str]]] = {}

    for issue_id, fm in issues.items():
        body = fm.get("_body", "")
        sen_refs, drawing_refs = _extract_refs_from_body(body)
        # 자기 자신 제외
        sen_refs = [r for r in sen_refs if r.upper() != issue_id]
        ref_map[issue_id] = {
            "sen_refs": sen_refs,
            "drawing_refs": drawing_refs,
        }

    # 연결 강도 계산 (양방향 참조)
    connections: Dict[Tuple[str, str], int] = defaultdict(int)
    for issue_id, refs in ref_map.items():
        for ref in refs["sen_refs"]:
            ref_upper = ref.upper().replace("_", "-")
            if ref_upper in issues:
                pair = tuple(sorted([issue_id, ref_upper]))
                connections[pair] += 1

    # 고아 이슈 (참조 없음)
    orphans = [
        issue_id for issue_id, refs in ref_map.items()
        if not refs["sen_refs"] and not refs["drawing_refs"]
    ]

    # 도면 참조 집계
    all_drawings: Dict[str, List[str]] = defaultdict(list)
    for issue_id, refs in ref_map.items():
        for dwg in refs["drawing_refs"]:
            all_drawings[dwg].append(issue_id)

    # 리포트 구성
    now = datetime.now()
    lines = [
        f"🔗 **이슈-도면-제작 연계 추적 맵**",
        f"━{'━' * 28}",
        f"📅 {now.strftime('%Y-%m-%d %H:%M')}",
        f"📝 분석 이슈: {len(issues)}건",
        "",
        "**[단계별 분포]**",
        f"  📋 이슈: {len(stage_map.get('이슈', []))}건",
        f"  📐 도면: {len(stage_map.get('도면', []))}건",
        f"  🏭 제작: {len(stage_map.get('제작', []))}건",
        "",
    ]

    # 주요 연결 (양방향 참조 Top 10)
    if connections:
        lines.append(f"**[주요 연계]** ({len(connections)}건)")
        sorted_conns = sorted(connections.items(), key=lambda x: x[1], reverse=True)
        for (a, b), strength in sorted_conns[:10]:
            stage_a = _classify_issue_stage(issues.get(a, {}))
            stage_b = _classify_issue_stage(issues.get(b, {}))
            lines.append(f"  {a}({stage_a}) ↔ {b}({stage_b})")
        if len(sorted_conns) > 10:
            lines.append(f"  ... 외 {len(sorted_conns)-10}건")
        lines.append("")

    # 도면번호 기반 연계
    multi_ref_drawings = {
        dwg: ids for dwg, ids in all_drawings.items()
        if len(ids) >= 2
    }
    if multi_ref_drawings:
        lines.append(f"**[도면 기반 연계]** (2건 이상 참조 도면: {len(multi_ref_drawings)}개)")
        for dwg, ids in sorted(multi_ref_drawings.items(), key=lambda x: len(x[1]), reverse=True)[:10]:
            lines.append(f"  📐 {dwg}: {', '.join(ids[:5])}")
        lines.append("")

    # 고아 이슈
    if orphans:
        lines.append(f"**[고아 이슈]** (연계 없음: {len(orphans)}건)")
        # 우선순위가 높은 것만 표시
        priority_orphans = []
        for oid in orphans:
            fm = issues.get(oid, {})
            pri = (fm.get("priority") or "normal").lower()
            if pri in ("critical", "high"):
                priority_orphans.append((oid, pri))

        if priority_orphans:
            lines.append(f"  ⚠️ 긴급/높음 우선순위: {len(priority_orphans)}건")
            for oid, pri in priority_orphans[:5]:
                lines.append(f"    {oid} ({pri})")
        else:
            lines.append(f"  (긴급/높음 우선순위 고아 이슈 없음)")

        lines.append(f"  전체 고아 이슈: {len(orphans)}건")
        lines.append("")

    # 영향도 분석: 제작 단계에 영향을 주는 이슈 체인
    fab_issues = stage_map.get("제작", [])
    impacting_issues: List[str] = []
    for fab_id in fab_issues:
        refs = ref_map.get(fab_id, {}).get("sen_refs", [])
        for ref in refs:
            ref_upper = ref.upper().replace("_", "-")
            if ref_upper in issues:
                stage = _classify_issue_stage(issues[ref_upper])
                if stage in ("이슈", "도면"):
                    status = (issues[ref_upper].get("status") or "open").lower()
                    if status == "open":
                        impacting_issues.append(f"{ref_upper}({stage}) → {fab_id}(제작)")

    if impacting_issues:
        lines.append(f"**[제작 영향 체인]** (미해결 이슈 → 제작)")
        for chain in impacting_issues[:10]:
            lines.append(f"  ⚠️ {chain}")
        if len(impacting_issues) > 10:
            lines.append(f"  ... 외 {len(impacting_issues)-10}건")
        lines.append("")

    # 텍스트 파일로 저장
    result_text = "\n".join(lines)
    files = []

    if task_dir:
        out_path = os.path.join(
            task_dir,
            f"연계추적맵_{now.strftime('%Y%m%d')}.txt",
        )
        try:
            tmp_path = out_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(result_text)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, out_path)
            files.append(out_path)
        except Exception:
            pass

    return {"result_text": result_text, "files": files}
