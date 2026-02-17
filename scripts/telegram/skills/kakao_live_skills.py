#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
카카오톡 실시간 스킬 모듈 (pywinauto 직접 제어)
=================================================
pywinauto UIA 백엔드로 카카오톡 PC 앱을 직접 제어.
MCP 의존성 없이 Step 2(python_runner)에서 직행 실행.

스킬 목록:
  - kakao_live_read: 실시간 대화 읽기 (클립보드 방식)
  - kakao_room_list: 열린 채팅방 목록 조회
  - kakao_reply_draft: 답장 초안 입력 (Enter 미입력 + 미리보기)
  - kakao_send_confirm: 답장 전송 확인 (Enter 누름)
  - kakao_send_cancel: 답장 취소 (입력 삭제)
  - kakao_context: 대화 맥락 분석 + 액션 아이템

보안:
  - Enter 키 자동 입력 금지 (2단계 확인 필수)
  - 메시지/채팅방 삭제 금지
"""

from __future__ import annotations

import re
import traceback
from typing import Dict


# ═══════════════════════════════════════════════════════════════
#  내부 헬퍼
# ═══════════════════════════════════════════════════════════════

def _parse_live_command(instruction: str) -> Dict:
    """카카오톡 라이브 명령어 파싱.

    Returns:
        {"target": str, "reply_text": str, "hours": int}
    """
    instruction = instruction.strip()

    # 키워드 접두사 제거
    prefixes = [
        "카톡실시간검색", "카톡답변제안", "카톡뭐라고할까",
        "카톡브리핑실시간", "카톡내보내기자동", "카톡자동저장",
        "카톡방목록", "카톡방리스트", "열린카톡",
        "카톡읽기", "카톡실시간", "실시간카톡", "카톡라이브", "카톡지금",
        "카톡보내", "카톡전송", "카톡입력",
        "카톡맥락", "카톡상황", "카톡답변",
        "카카오읽기", "카카오실시간",
        "카톡", "카카오", "kakao",
    ]
    for prefix in prefixes:
        lower = instruction.lower()
        if lower.startswith(prefix):
            instruction = instruction[len(prefix):].strip()
            break

    if not instruction:
        return {"target": "", "reply_text": "", "hours": 0}

    # 시간 파싱: "3시간", "24h"
    hours = 0
    h_match = re.search(r'(\d+)\s*(?:시간|h|hour)', instruction, re.IGNORECASE)
    if h_match:
        hours = int(h_match.group(1))
        instruction = instruction[:h_match.start()].strip() + " " + instruction[h_match.end():].strip()
        instruction = instruction.strip()

    # "카톡보내 P5현장 답장내용" → target="P5현장", reply_text="답장내용"
    # 첫 번째 단어를 target으로, 나머지를 reply_text로 분리
    parts = instruction.split(maxsplit=1)
    target = parts[0] if parts else ""
    reply_text = parts[1] if len(parts) > 1 else ""

    return {"target": target, "reply_text": reply_text, "hours": hours}


# ═══════════════════════════════════════════════════════════════
#  kakao_live_read — 실시간 대화 읽기
# ═══════════════════════════════════════════════════════════════

def run_kakao_live_read(context: dict) -> dict:
    """카카오톡 PC 앱에서 실시간 대화 읽기 (클립보드 방식).

    흐름:
      1. 단일 PowerShell 스크립트로 카카오톡 활성화
      2. Ctrl+A → Ctrl+C → Get-Clipboard (모두 한 프로세스에서)
      3. 대화 텍스트 파싱 → 결과 반환
    """
    send_progress = context.get("send_progress", lambda x: None)
    combined = context.get("combined", {})
    instruction = combined.get("combined_instruction", "")
    task_dir = context.get("task_dir", "")

    try:
        from scripts.telegram.kakao_desktop import read_kakao_clipboard_direct

        cmd = _parse_live_command(instruction)
        chat_room = cmd["target"] or "P5"

        send_progress(f"💬 카카오톡 '{chat_room}' 채팅방 실시간 읽기 중...")

        result = read_kakao_clipboard_direct(
            chat_room=chat_room,
            task_dir=task_dir,
            send_progress=send_progress,
        )

        return result

    except Exception as e:
        return {
            "result_text": f"❌ 카톡 실시간 읽기 오류: {e}\n{traceback.format_exc()[-500:]}",
            "files": [],
        }


# ═══════════════════════════════════════════════════════════════
#  kakao_room_list — 채팅방 목록
# ═══════════════════════════════════════════════════════════════

def run_kakao_room_list(context: dict) -> dict:
    """카카오톡 PC 앱에서 보이는 채팅방 목록 조회."""
    send_progress = context.get("send_progress", lambda x: None)
    task_dir = context.get("task_dir", "")

    try:
        from scripts.telegram.kakao_pywinauto import list_rooms

        return list_rooms(
            task_dir=task_dir,
            send_progress=send_progress,
        )

    except Exception as e:
        return {
            "result_text": f"❌ 카톡 방 목록 조회 오류: {e}\n{traceback.format_exc()[-500:]}",
            "files": [],
        }


# ═══════════════════════════════════════════════════════════════
#  kakao_reply_draft — 답장 초안 (2단계 확인)
# ═══════════════════════════════════════════════════════════════

def run_kakao_reply_draft(context: dict) -> dict:
    """답장 초안 입력 (Enter 미입력) + 미리보기.

    2단계 확인:
      Phase 1: 텍스트 입력 + 스크린샷 → 텔레그램에 미리보기 전송
      Phase 2: 사용자가 '보내' → run_kakao_send_confirm()
    """
    send_progress = context.get("send_progress", lambda x: None)
    combined = context.get("combined", {})
    instruction = combined.get("combined_instruction", "")
    task_dir = context.get("task_dir", "")
    chat_id = combined.get("chat_id", 0)

    try:
        from scripts.telegram.kakao_pywinauto import draft_reply
        from scripts.telegram.kakao_desktop import (
            save_pending_reply,
            has_pending_reply,
        )

        # 이미 대기 중인 답장이 있으면 경고
        if has_pending_reply():
            return {
                "result_text": (
                    "⚠️ 이미 대기 중인 카톡 답장이 있습니다.\n"
                    "'보내' 또는 '취소'로 먼저 처리해주세요."
                ),
                "files": [],
            }

        cmd = _parse_live_command(instruction)
        chat_room = cmd["target"]
        reply_text = cmd["reply_text"]

        if not chat_room:
            return {
                "result_text": (
                    "⚠️ 채팅방 이름을 지정해주세요.\n"
                    "예: 카톡보내 P5현장 내일 회의 10시입니다"
                ),
                "files": [],
            }

        if not reply_text:
            return {
                "result_text": (
                    "⚠️ 보낼 메시지를 입력해주세요.\n"
                    "예: 카톡보내 P5현장 내일 회의 10시입니다"
                ),
                "files": [],
            }

        send_progress(f"✏️ '{chat_room}' 채팅방에 답장 초안 입력 중...")

        # pywinauto로 텍스트 입력 (Enter 안 누름)
        result = draft_reply(
            chat_room=chat_room,
            text=reply_text,
            task_dir=task_dir,
            send_progress=send_progress,
        )

        # 대기 상태 저장
        save_pending_reply(chat_room, reply_text, chat_id, task_dir)

        # 결과에 확인 안내 추가
        result["result_text"] = (
            f"✏️ 카카오톡 답장 초안 ({chat_room})\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{reply_text}\n\n"
            f"📸 미리보기 스크린샷 첨부\n\n"
            f"⚠️ 아직 전송하지 않았습니다.\n"
            f"✅ 보내려면 '보내' 라고 답장\n"
            f"❌ 취소하려면 '취소' 라고 답장\n"
            f"⏰ 10분 후 자동 취소됩니다."
        )

        return result

    except Exception as e:
        return {
            "result_text": f"❌ 카톡 답장 초안 오류: {e}\n{traceback.format_exc()[-500:]}",
            "files": [],
        }


# ═══════════════════════════════════════════════════════════════
#  kakao_send_confirm — 답장 전송 확인
# ═══════════════════════════════════════════════════════════════

def run_kakao_send_confirm(context: dict) -> dict:
    """대기 중인 카톡 답장 전송 — Enter 누름."""
    send_progress = context.get("send_progress", lambda x: None)
    task_dir = context.get("task_dir", "")

    try:
        from scripts.telegram.kakao_pywinauto import confirm_send
        from scripts.telegram.kakao_desktop import (
            load_pending_reply,
            clear_pending_reply,
        )

        pending = load_pending_reply()
        if not pending:
            return {
                "result_text": "ℹ️ 대기 중인 카톡 답장이 없습니다.",
                "files": [],
            }

        chat_room = pending["chat_room"]
        reply_text = pending["reply_text"]
        # 이전 task_dir 사용 (스크린샷 저장 위치)
        original_task_dir = pending.get("task_dir", task_dir)

        send_progress(f"📤 '{chat_room}' 채팅방에 메시지 전송 중...")

        result = confirm_send(
            task_dir=original_task_dir,
            send_progress=send_progress,
        )

        # 대기 상태 삭제
        clear_pending_reply()

        result["result_text"] = (
            f"✅ 메시지 전송 완료!\n\n"
            f"채팅방: {chat_room}\n"
            f"내용: {reply_text}\n\n"
            f"{result.get('result_text', '')}"
        )

        return result

    except Exception as e:
        return {
            "result_text": f"❌ 카톡 전송 확인 오류: {e}\n{traceback.format_exc()[-500:]}",
            "files": [],
        }


# ═══════════════════════════════════════════════════════════════
#  kakao_send_cancel — 답장 취소
# ═══════════════════════════════════════════════════════════════

def run_kakao_send_cancel(context: dict) -> dict:
    """대기 중인 카톡 답장 취소 — 입력 삭제."""
    send_progress = context.get("send_progress", lambda x: None)
    task_dir = context.get("task_dir", "")

    try:
        from scripts.telegram.kakao_pywinauto import cancel_send
        from scripts.telegram.kakao_desktop import (
            load_pending_reply,
            clear_pending_reply,
        )

        pending = load_pending_reply()
        if not pending:
            return {
                "result_text": "ℹ️ 대기 중인 카톡 답장이 없습니다.",
                "files": [],
            }

        chat_room = pending["chat_room"]
        original_task_dir = pending.get("task_dir", task_dir)

        send_progress(f"❌ '{chat_room}' 답장 취소 중...")

        cancel_send(
            task_dir=original_task_dir,
            send_progress=send_progress,
        )

        # 대기 상태 삭제
        clear_pending_reply()

        return {
            "result_text": f"❌ 카톡 답장이 취소되었습니다.\n채팅방: {chat_room}",
            "files": [],
        }

    except Exception as e:
        return {
            "result_text": f"❌ 카톡 취소 오류: {e}\n{traceback.format_exc()[-500:]}",
            "files": [],
        }


# ═══════════════════════════════════════════════════════════════
#  kakao_context — 대화 맥락 분석
# ═══════════════════════════════════════════════════════════════

def run_kakao_context(context: dict) -> dict:
    """채팅방 대화 맥락 분석 + 액션 아이템 도출.

    클립보드로 대화 읽기 → 텍스트 분석:
      - 주요 토픽
      - 결정 사항
      - 미완료/대기 사항
      - 응답 필요 항목
      - 추천 답변 방향
    """
    send_progress = context.get("send_progress", lambda x: None)
    combined = context.get("combined", {})
    instruction = combined.get("combined_instruction", "")
    task_dir = context.get("task_dir", "")

    try:
        from scripts.telegram.kakao_desktop import read_kakao_clipboard_direct

        cmd = _parse_live_command(instruction)
        chat_room = cmd["target"] or "P5"

        send_progress(f"🧠 카카오톡 '{chat_room}' 대화 맥락 분석 중...")

        # 먼저 클립보드 읽기
        result = read_kakao_clipboard_direct(
            chat_room=chat_room,
            task_dir=task_dir,
            send_progress=send_progress,
        )

        return result

    except Exception as e:
        return {
            "result_text": f"❌ 카톡 맥락 분석 오류: {e}\n{traceback.format_exc()[-500:]}",
            "files": [],
        }
