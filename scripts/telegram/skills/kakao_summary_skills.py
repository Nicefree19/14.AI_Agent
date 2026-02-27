#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
카카오톡 자동 요약 스킬 모듈

스킬:
  - run_kakao_daily_summary: 카카오톡 업무방 대화 읽기 → 핵심 요약 리포트
"""

from __future__ import annotations

import os
import re
import traceback
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from scripts.telegram.config import PROJECT_ROOT


def _classify_message(text: str) -> str:
    """메시지를 카테고리로 분류."""
    text_lower = text.lower()

    # 결정사항
    if any(kw in text_lower for kw in ["결정", "확정", "합의", "승인", "결론"]):
        return "결정사항"
    # 요청/지시
    if any(kw in text_lower for kw in ["요청", "부탁", "해주세요", "해줘", "진행해", "확인해"]):
        return "요청사항"
    # 일정 관련
    if any(kw in text_lower for kw in ["일정", "납기", "마감", "기한", "스케줄", "출도"]):
        return "일정변경"
    # 이슈/문제
    if any(kw in text_lower for kw in ["이슈", "문제", "오류", "간섭", "불가", "지연", "변경"]):
        return "이슈/문제"
    # 공유/참고
    if any(kw in text_lower for kw in ["공유", "참고", "첨부", "FYI", "전달"]):
        return "정보공유"
    return "일반대화"


def _extract_sen_refs(text: str) -> List[str]:
    """SEN-xxx 이슈 참조 추출."""
    return re.findall(r"SEN[-_]\d{3,}", text, re.IGNORECASE)


def run_kakao_daily_summary(context: dict) -> dict:
    """카카오톡 업무방 대화를 읽고 핵심 내용을 요약.

    1. pywinauto로 카카오톡 대화 읽기 시도
    2. 메시지 분류 (결정/요청/일정/이슈/공유/일반)
    3. 카테고리별 요약 리포트 생성
    4. 미등록 이슈 후보 제안
    """
    send_progress = context.get("send_progress", lambda x: None)
    task_dir = context.get("task_dir", "")

    send_progress("💬 카카오톡 업무방 메시지 읽기 중...")

    # pywinauto 카카오톡 읽기 시도
    messages = []
    room_name = "알 수 없음"

    try:
        from scripts.telegram.kakao_pywinauto import read_chat
        raw_text = read_chat()

        if not raw_text or raw_text.startswith("오류") or raw_text.startswith("❌"):
            return {
                "result_text": (
                    "⚠️ 카카오톡 PC 앱이 실행되지 않았거나 "
                    "열린 채팅방이 없습니다.\n\n"
                    "카카오톡을 열고 업무방을 선택한 후 다시 시도해주세요."
                ),
                "files": [],
            }

        # 텍스트를 줄 단위로 파싱
        lines = raw_text.strip().split("\n")

        # 첫 줄이 방 이름일 수 있음
        if lines and not lines[0].startswith("["):
            room_name = lines[0].strip()
            lines = lines[1:]

        for line in lines:
            line = line.strip()
            if not line:
                continue
            messages.append(line)

    except ImportError:
        return {
            "result_text": (
                "⚠️ 카카오톡 읽기 모듈(kakao_pywinauto)을 로드할 수 없습니다."
            ),
            "files": [],
        }
    except Exception as e:
        return {
            "result_text": f"⚠️ 카카오톡 읽기 실패: {e}",
            "files": [],
        }

    if not messages:
        return {
            "result_text": "⚠️ 읽을 수 있는 메시지가 없습니다.",
            "files": [],
        }

    send_progress(f"💬 메시지 {len(messages)}건 분석 중...")

    # 메시지 분류
    categorized: Dict[str, List[str]] = defaultdict(list)
    sen_refs: List[str] = []

    for msg in messages:
        cat = _classify_message(msg)
        categorized[cat].append(msg)
        sen_refs.extend(_extract_sen_refs(msg))

    # 요약 리포트 구성
    now = datetime.now()
    lines = [
        f"💬 **카카오톡 업무방 요약 리포트**",
        f"━{'━' * 28}",
        f"📅 {now.strftime('%Y-%m-%d %H:%M')}",
        f"💬 채팅방: {room_name}",
        f"📝 메시지: {len(messages)}건",
        "",
    ]

    # 중요 카테고리 순서
    priority_cats = ["결정사항", "요청사항", "일정변경", "이슈/문제", "정보공유"]
    cat_icons = {
        "결정사항": "✅",
        "요청사항": "📋",
        "일정변경": "📅",
        "이슈/문제": "⚠️",
        "정보공유": "ℹ️",
        "일반대화": "💬",
    }

    for cat in priority_cats:
        msgs = categorized.get(cat, [])
        if msgs:
            icon = cat_icons.get(cat, "•")
            lines.append(f"**{icon} {cat}** ({len(msgs)}건)")
            for msg in msgs[:5]:  # 최대 5건
                lines.append(f"  • {msg[:100]}")
            if len(msgs) > 5:
                lines.append(f"  ... 외 {len(msgs)-5}건")
            lines.append("")

    # 일반대화는 건수만
    general = categorized.get("일반대화", [])
    if general:
        lines.append(f"**💬 일반대화**: {len(general)}건 (요약 생략)")
        lines.append("")

    # SEN 이슈 참조
    if sen_refs:
        unique_refs = sorted(set(sen_refs))
        lines.append(f"**🔗 언급된 이슈 코드** ({len(unique_refs)}건)")
        lines.append(f"  {', '.join(unique_refs)}")
        lines.append("")

    # 미등록 이슈 후보 (결정사항/요청사항 중 SEN 없는 것)
    unregistered = []
    for cat in ["결정사항", "요청사항"]:
        for msg in categorized.get(cat, []):
            if not _extract_sen_refs(msg):
                unregistered.append(msg[:80])

    if unregistered:
        lines.append(f"**💡 미등록 이슈 후보** ({len(unregistered)}건)")
        for item in unregistered[:3]:
            lines.append(f"  → {item}")
        lines.append("")

    result_text = "\n".join(lines)

    # 텍스트 파일로도 저장
    files = []
    if task_dir:
        out_path = os.path.join(
            task_dir,
            f"카톡요약_{now.strftime('%Y%m%d_%H%M')}.txt"
        )
        try:
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(result_text)
            files.append(out_path)
        except Exception:
            pass

    return {"result_text": result_text, "files": files}
