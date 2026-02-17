#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
카카오톡 스킬 모듈

- kakao_chat: P5 채팅방 목록 조회 / 특정 채팅방 메시지 읽기
- kakao_search: P5 채팅방 내 키워드 검색
- kakao_summary: 채팅방 대화 요약 및 답장 방향 제시
"""

from __future__ import annotations

import re
import traceback
from typing import Dict, List

from scripts.telegram.skill_utils import truncate_text


# ═══════════════════════════════════════════════════════════════
#  내부 헬퍼
# ═══════════════════════════════════════════════════════════════

def _parse_kakao_command(instruction: str) -> Dict:
    """카카오 명령어 파싱.

    Returns:
        {"action": str, "target": str, "keyword": str, "hours": int}
    """
    instruction = instruction.strip()

    # 키워드 접두사 제거
    for prefix in ["카톡검색", "카카오검색", "카톡요약", "카카오요약",
                    "카톡답장", "카카오답장", "카톡목록", "카카오목록",
                    "카톡확인", "카카오확인", "카톡", "카카오", "kakao"]:
        if instruction.startswith(prefix):
            instruction = instruction[len(prefix):].strip()
            break

    # "목록" 만 남으면 목록 조회
    if not instruction or instruction in ("목록", "리스트", "list"):
        return {"action": "list", "target": "", "keyword": "", "hours": 0}

    # "최근" → 가장 최근 채팅방
    if instruction in ("최근", "recent", "last"):
        return {"action": "recent", "target": "", "keyword": "", "hours": 24}

    # 시간 파싱: "3시간", "24h", "48시간"
    hours = 0
    h_match = re.search(r'(\d+)\s*(?:시간|h|hour)', instruction, re.IGNORECASE)
    if h_match:
        hours = int(h_match.group(1))
        instruction = instruction[:h_match.start()].strip() + " " + instruction[h_match.end():].strip()
        instruction = instruction.strip()

    # 남은 텍스트가 있으면 target으로 사용
    return {"action": "read", "target": instruction, "keyword": "", "hours": hours}


def _format_chat_list(rooms: List[Dict]) -> str:
    """채팅방 목록을 텔레그램 텍스트로 포맷."""
    if not rooms:
        return "📭 P5 채팅방 데이터가 없습니다."

    lines = [f"💬 P5 채팅방 목록 ({len(rooms)}개)"]
    lines.append("━" * 28)

    for i, room in enumerate(rooms, 1):
        name = room["chat_name"]
        count = room["msg_count"]
        last = room.get("last_ts", "")[:10]  # YYYY-MM-DD
        lines.append(f"{i}. {name}")
        lines.append(f"   📝 {count:,}건 | 마지막: {last}")

    return "\n".join(lines)


def _format_messages(messages: List[Dict], chat_name: str, limit: int = 30) -> str:
    """메시지 목록을 텔레그램 텍스트로 포맷."""
    if not messages:
        return f"📭 '{chat_name}' 채팅방에 메시지가 없습니다."

    shown = messages[-limit:] if len(messages) > limit else messages
    lines = [f"💬 {chat_name} (최근 {len(shown)}건 / 전체 {len(messages)}건)"]
    lines.append("━" * 28)

    for msg in shown:
        ts = msg["timestamp"][:16].replace("T", " ")  # YYYY-MM-DD HH:MM
        sender = msg["sender"]
        text = msg["text"]
        if len(text) > 80:
            text = text[:77] + "..."
        lines.append(f"[{ts}] {sender}")
        lines.append(f"  {text}")

    return "\n".join(lines)


def _format_search_results(results: List[Dict]) -> str:
    """검색 결과를 텔레그램 텍스트로 포맷."""
    if not results:
        return "🔍 검색 결과가 없습니다."

    lines = [f"🔍 검색 결과 ({len(results)}건)"]
    lines.append("━" * 28)

    for i, r in enumerate(results, 1):
        ts = r["timestamp"][:16].replace("T", " ")
        chat = r["chat_name"]
        sender = r["sender"]
        text = r["text"]
        if len(text) > 60:
            text = text[:57] + "..."
        lines.append(f"{i}. [{chat}] {ts}")
        lines.append(f"   {sender}: {text}")

    return "\n".join(lines)


def _format_summary(summary: Dict) -> str:
    """요약 데이터를 텔레그램 텍스트로 포맷."""
    chat_name = summary["chat_name"]
    total = summary["total_count"]
    period = summary["period"]
    participants = summary.get("participants", {})
    topics = summary.get("topics", [])

    lines = [f"📊 {chat_name} 요약 ({period})"]
    lines.append("━" * 28)
    lines.append(f"총 {total}건의 메시지")
    lines.append("")

    if participants:
        lines.append("👥 참여자:")
        for name, count in list(participants.items())[:10]:
            lines.append(f"  • {name}: {count}건")
        lines.append("")

    if topics:
        lines.append("🏷️ 핵심 키워드:")
        lines.append("  " + ", ".join(topics))
        lines.append("")

    # 최근 5개 메시지 미리보기
    msgs = summary.get("messages", [])
    if msgs:
        recent = msgs[-5:]
        lines.append("💬 최근 대화:")
        for m in recent:
            ts = m["timestamp"][:16].replace("T", " ")
            text = m["text"]
            if len(text) > 50:
                text = text[:47] + "..."
            lines.append(f"  [{ts}] {m['sender']}: {text}")

    return "\n".join(lines)


def _fallback_message() -> str:
    """데이터 없을 때 안내 메시지."""
    from scripts.telegram.kakao_utils import get_export_guide
    return get_export_guide()


# ═══════════════════════════════════════════════════════════════
#  kakao_chat — 채팅방 목록 / 메시지 읽기
# ═══════════════════════════════════════════════════════════════

def run_kakao_chat(context: dict) -> dict:
    """카카오톡 P5 채팅방 조회/메시지 읽기.

    명령 파싱:
    - "카톡 목록" / "카톡목록" → P5 채팅방 목록
    - "카톡 P5 현장" → "P5 현장" 포함 채팅방의 최근 메시지
    - "카톡 최근" → 가장 최근 활성 P5 채팅방 메시지
    """
    send_progress = context.get("send_progress", lambda x: None)
    combined = context.get("combined", {})
    instruction = combined.get("combined_instruction", "")

    try:
        from scripts.telegram.kakao_utils import (
            is_available, list_chat_rooms, get_chat_messages, refresh_index
        )

        # 가용성 확인
        available, msg = is_available()
        if not available:
            return {"result_text": f"⚠️ 카카오톡 데이터 미준비\n\n{msg}\n\n{_fallback_message()}", "files": []}

        send_progress("💬 카카오톡 데이터 조회 중...")

        cmd = _parse_kakao_command(instruction)

        if cmd["action"] == "list":
            # 인덱스 갱신 후 목록 표시
            refresh_index()
            rooms = list_chat_rooms()
            result = _format_chat_list(rooms)

        elif cmd["action"] == "recent":
            # 가장 최근 활성 채팅방 메시지
            rooms = list_chat_rooms(limit=1)
            if not rooms:
                result = "📭 P5 채팅방 데이터가 없습니다.\n\n" + _fallback_message()
            else:
                messages = get_chat_messages(rooms[0]["filepath"], limit=30)
                result = _format_messages(messages, rooms[0]["chat_name"])

        else:
            # 특정 채팅방 메시지 읽기
            target = cmd["target"]
            hours = cmd["hours"]
            messages = get_chat_messages(target, limit=50, since_hours=hours)
            if messages:
                chat_name = messages[0]["chat_name"]
                result = _format_messages(messages, chat_name)
            else:
                # 매치 실패 시 목록 표시
                rooms = list_chat_rooms()
                result = (
                    f"❓ '{target}' 채팅방을 찾을 수 없습니다.\n\n"
                    + _format_chat_list(rooms)
                )

        return {"result_text": truncate_text(result, 3500), "files": []}

    except Exception as e:
        log_msg = traceback.format_exc()
        return {"result_text": f"❌ 카카오톡 조회 오류: {e}\n\n{_fallback_message()}", "files": []}


# ═══════════════════════════════════════════════════════════════
#  kakao_search — P5 채팅방 내 키워드 검색
# ═══════════════════════════════════════════════════════════════

def run_kakao_search(context: dict) -> dict:
    """P5 채팅방 범위 내 키워드 검색.

    명령 파싱:
    - "카톡검색 PSRC 납품" → P5 채팅방들에서 "PSRC 납품" 검색
    - "카카오검색 SEN-070" → P5 채팅방들에서 "SEN-070" 검색
    """
    send_progress = context.get("send_progress", lambda x: None)
    combined = context.get("combined", {})
    instruction = combined.get("combined_instruction", "")

    try:
        from scripts.telegram.kakao_utils import is_available, search_messages

        available, msg = is_available()
        if not available:
            return {"result_text": f"⚠️ 카카오톡 데이터 미준비\n\n{msg}\n\n{_fallback_message()}", "files": []}

        # 검색 키워드 추출
        keyword = instruction.strip()
        for prefix in ["카톡검색", "카카오검색", "kakao search", "kakao"]:
            if keyword.lower().startswith(prefix):
                keyword = keyword[len(prefix):].strip()
                break

        if not keyword:
            return {"result_text": "❓ 검색어를 입력해주세요.\n예: 카톡검색 PSRC 납품", "files": []}

        send_progress(f"🔍 P5 채팅방에서 '{keyword}' 검색 중...")

        results = search_messages(keyword, limit=20)
        result = _format_search_results(results)

        if not results:
            result += f"\n\n💡 '{keyword}'에 대한 검색 결과가 없습니다."

        return {"result_text": truncate_text(result, 3500), "files": []}

    except Exception as e:
        return {"result_text": f"❌ 카카오톡 검색 오류: {e}", "files": []}


# ═══════════════════════════════════════════════════════════════
#  kakao_summary — 채팅방 요약 / 답장 방향
# ═══════════════════════════════════════════════════════════════

def run_kakao_summary(context: dict) -> dict:
    """P5 채팅방 업무 맥락 요약 + 답장 방향 제시.

    명령 파싱:
    - "카톡요약 P5 현장" → 최근 대화 요약
    - "카톡답장 구조검토 PSRC 의견" → 답장 초안 생성 방향
    """
    send_progress = context.get("send_progress", lambda x: None)
    combined = context.get("combined", {})
    instruction = combined.get("combined_instruction", "")

    try:
        from scripts.telegram.kakao_utils import is_available, get_chat_summary, list_chat_rooms

        available, msg = is_available()
        if not available:
            return {"result_text": f"⚠️ 카카오톡 데이터 미준비\n\n{msg}\n\n{_fallback_message()}", "files": []}

        # 대상 채팅방 파싱
        target = instruction.strip()
        is_reply = False
        for prefix in ["카톡답장", "카카오답장"]:
            if target.startswith(prefix):
                target = target[len(prefix):].strip()
                is_reply = True
                break
        for prefix in ["카톡요약", "카카오요약", "카톡", "카카오"]:
            if target.startswith(prefix):
                target = target[len(prefix):].strip()
                break

        if not target:
            # 가장 최근 채팅방 자동 선택
            rooms = list_chat_rooms(limit=1)
            if rooms:
                target = rooms[0]["filepath"]
            else:
                return {"result_text": "📭 P5 채팅방 데이터가 없습니다.\n\n" + _fallback_message(), "files": []}

        send_progress("📊 대화 분석 중...")

        summary = get_chat_summary(target, hours=48, max_messages=300)
        result = _format_summary(summary)

        if is_reply and summary.get("total_count", 0) > 0:
            result += "\n\n" + "━" * 28
            result += "\n✏️ 답장 방향:"
            topics = summary.get("topics", [])
            participants = list(summary.get("participants", {}).keys())
            if topics:
                result += f"\n  • 주요 토픽: {', '.join(topics[:3])}"
            if participants:
                result += f"\n  • 주요 참여자: {', '.join(participants[:3])}"
            result += "\n  • 최근 대화 흐름을 바탕으로 답변을 작성하세요."

        return {"result_text": truncate_text(result, 3500), "files": []}

    except Exception as e:
        return {"result_text": f"❌ 카카오톡 요약 오류: {e}", "files": []}
