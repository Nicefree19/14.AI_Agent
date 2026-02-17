#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
카카오톡 PC 앱 pywinauto 직접 제어 모듈
=========================================
MCP 의존성 없이 pywinauto UIA 백엔드로 카카오톡 PC 앱을
직접 제어하는 순수 Python 모듈.

3-Tier Fallback:
  Tier 1: pywinauto UIA (modern, Korean text support)
  Tier 2: PowerShell Win32 API (기존 검증된 패턴)
  Tier 3: ctypes/SendMessage (최후 수단)

Executor 계약: → {"result_text": str, "files": list[str]}

보안:
  - Enter 키 자동 입력 금지 — confirm_send()에서만 허용
  - 메시지/채팅방 삭제 금지
  - 파일 전송 금지 (텍스트만)
  - 프리플라이트 체크: KakaoTalk 미실행 시 즉시 에러
"""

from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import time
import traceback
from pathlib import Path
from typing import Optional, Tuple

log = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
#  상수
# ═══════════════════════════════════════════════════════════════

_BASE_DIR = Path(__file__).resolve().parent.parent.parent
_TELEGRAM_DATA = _BASE_DIR / "telegram_data"

# 안전 규칙 (모듈 레벨)
_MAX_REPLY_LENGTH = 2000  # 최대 메시지 길이
_ACTIVATE_RETRIES = 3     # 창 활성화 재시도 횟수

# 중앙화된 타임아웃 (config.py에서 가져옴)
from scripts.telegram.config import (  # noqa: E402
    KAKAO_CLIPBOARD_WAIT_SEC as _CLIPBOARD_WAIT_SEC,
    KAKAO_PS_TIMEOUT_SEC as _PS_TIMEOUT_SEC,
)


# ═══════════════════════════════════════════════════════════════
#  예외
# ═══════════════════════════════════════════════════════════════

class KakaoNotRunningError(RuntimeError):
    """카카오톡 PC 앱이 실행되지 않았을 때."""
    pass


class KakaoActivationError(RuntimeError):
    """카카오톡 창 활성화 실패."""
    pass


# ═══════════════════════════════════════════════════════════════
#  프리플라이트 체크
# ═══════════════════════════════════════════════════════════════

def _preflight() -> None:
    """카카오톡 프로세스 확인. 미실행 시 KakaoNotRunningError.

    feature flag "kakao_preflight" 가드:
      OFF → fail-open (기존 동작: 확인 실패 시 조용히 진행)
      ON  → fail-closed (확인 실패 시 예외 raise)
    """
    from scripts.telegram.config import is_enabled

    try:
        result = subprocess.run(
            ["powershell", "-Command",
             "if(Get-Process KakaoTalk -ErrorAction SilentlyContinue)"
             "{'RUNNING'}else{'NOT_RUNNING'}"],
            capture_output=True, text=True, timeout=_PS_TIMEOUT_SEC,
        )
        if "NOT_RUNNING" in result.stdout:
            raise KakaoNotRunningError(
                "카카오톡 PC 앱이 실행되지 않았습니다.\n"
                "카카오톡을 먼저 실행한 후 다시 시도해주세요."
            )
    except KakaoNotRunningError:
        raise
    except subprocess.TimeoutExpired:
        if is_enabled("kakao_preflight"):
            raise KakaoNotRunningError("카카오톡 프리플라이트 타임아웃")
        log.warning("KakaoTalk 프로세스 확인 타임아웃 (fail-open)")
    except Exception as exc:
        if is_enabled("kakao_preflight"):
            raise KakaoNotRunningError(f"카카오톡 프리플라이트 실패: {exc}")
        log.warning(f"KakaoTalk 프로세스 확인 실패 (fail-open): {exc}")


def _error_result(msg: str) -> dict:
    """표준 에러 결과 딕셔너리."""
    return {"result_text": msg, "files": []}


# ═══════════════════════════════════════════════════════════════
#  Tier 1: pywinauto UIA 연결
# ═══════════════════════════════════════════════════════════════

def _connect_kakao():
    """pywinauto UIA 백엔드로 KakaoTalk.exe 연결.

    Returns:
        (app, dlg) — Application 객체, 메인 윈도우 래퍼
    Raises:
        ImportError: pywinauto 미설치
        Exception: 연결 실패
    """
    from pywinauto import Application
    app = Application(backend='uia').connect(path='KakaoTalk.exe')
    dlg = app.window(title_re='.*')
    # 최소한의 검증: 메인 윈도우가 존재하는지
    dlg.wait('visible', timeout=3)
    return app, dlg


def _find_edit_box(dlg):
    """메시지 입력 텍스트박스 탐색 (UIA Edit control).

    카카오톡 PC의 메시지 입력란은 class_name='RICHEDIT60W' 또는 'Edit'.
    채팅방이 열려있을 때만 존재.
    """
    try:
        # 채팅방 열림 상태의 입력란: RICHEDIT60W (주로 사용)
        edit = dlg.child_window(class_name='RICHEDIT60W')
        if edit.exists(timeout=1):
            return edit
    except Exception:
        pass

    try:
        # Fallback: 일반 Edit 컨트롤 (검색창일 수 있으므로 크기로 구분)
        edits = dlg.descendants(control_type='Edit', class_name='Edit')
        for e in edits:
            rect = e.rectangle()
            # 입력란은 보통 넓이 > 200, 높이 20-40
            if rect.width() > 200 and 15 < rect.height() < 60:
                return e
    except Exception:
        pass

    return None


def _get_kakao_window_rect(dlg) -> Optional[Tuple[int, int, int, int]]:
    """카카오톡 메인 윈도우의 (left, top, right, bottom) 반환."""
    try:
        rect = dlg.rectangle()
        return (rect.left, rect.top, rect.right, rect.bottom)
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════
#  Tier 2: PowerShell Win32 활성화 (검증됨)
# ═══════════════════════════════════════════════════════════════

def _activate_via_powershell() -> bool:
    """PowerShell AppActivate로 카카오톡 활성화."""
    try:
        result = subprocess.run(
            ["powershell", "-Command",
             "$wsh=New-Object -ComObject WScript.Shell;"
             "$proc=Get-Process KakaoTalk -EA SilentlyContinue|Select -First 1;"
             "if($proc){$wsh.AppActivate($proc.Id);'OK'}else{'FAIL'}"],
            capture_output=True, text=True, timeout=_PS_TIMEOUT_SEC,
        )
        return "OK" in result.stdout
    except Exception as exc:
        log.warning(f"PowerShell 활성화 실패: {exc}")
        return False


def _activate_kakao() -> bool:
    """카카오톡 창 활성화 (Tier 1 → Tier 2 fallback).

    Returns:
        True if successfully activated
    """
    # Tier 1: pywinauto
    try:
        _, dlg = _connect_kakao()
        dlg.set_focus()
        time.sleep(0.3)
        return True
    except Exception as exc:
        log.debug(f"pywinauto 활성화 실패, PowerShell fallback: {exc}")

    # Tier 2: PowerShell
    for attempt in range(_ACTIVATE_RETRIES):
        if _activate_via_powershell():
            time.sleep(0.5)
            return True
        time.sleep(0.3)

    return False


# ═══════════════════════════════════════════════════════════════
#  Tier 3: ctypes / SendKeys 헬퍼
# ═══════════════════════════════════════════════════════════════

def _send_keys_via_powershell(keys: str) -> bool:
    """PowerShell SendKeys로 키 입력."""
    try:
        result = subprocess.run(
            ["powershell", "-Command",
             f"Add-Type -AssemblyName System.Windows.Forms;"
             f"[System.Windows.Forms.SendKeys]::SendWait('{keys}')"],
            capture_output=True, text=True, timeout=_PS_TIMEOUT_SEC,
        )
        return result.returncode == 0
    except Exception as exc:
        log.warning(f"SendKeys 실패: {exc}")
        return False


def _type_text_via_powershell(text: str) -> bool:
    """PowerShell로 텍스트 입력 (clipboard paste 방식).

    한글 입력 호환을 위해 클립보드에 복사 후 Ctrl+V로 붙여넣기.
    """
    try:
        # 클립보드에 텍스트 설정
        escaped = text.replace("'", "''")
        result = subprocess.run(
            ["powershell", "-Command",
             f"Set-Clipboard -Value '{escaped}';"
             f"Add-Type -AssemblyName System.Windows.Forms;"
             f"[System.Windows.Forms.SendKeys]::SendWait('^v')"],
            capture_output=True, text=True, timeout=_PS_TIMEOUT_SEC,
        )
        return result.returncode == 0
    except Exception as exc:
        log.warning(f"텍스트 입력 실패: {exc}")
        return False


# ═══════════════════════════════════════════════════════════════
#  스크린샷 캡처
# ═══════════════════════════════════════════════════════════════

def take_screenshot(task_dir: str, name: str = "screenshot") -> dict:
    """카카오톡 스크린샷 캡처.

    Args:
        task_dir: 저장 디렉토리
        name: 파일명 프리픽스 (확장자 제외)

    Returns:
        {"result_text": str, "files": list[str]}
    """
    if not task_dir or not os.path.isdir(task_dir):
        return _error_result("⚠️ 작업 디렉토리가 유효하지 않습니다.")

    save_path = os.path.join(task_dir, f"{name}.png")

    try:
        result = subprocess.run(
            ["powershell", "-Command",
             "Add-Type -AssemblyName System.Windows.Forms;"
             "$s=[Windows.Forms.Screen]::PrimaryScreen.Bounds;"
             "$b=New-Object Drawing.Bitmap($s.Width,$s.Height);"
             "[Drawing.Graphics]::FromImage($b).CopyFromScreen(0,0,0,0,$b.Size);"
             f"$b.Save('{save_path}');"
             "'CAPTURED'"],
            capture_output=True, text=True, timeout=10,
        )
        if "CAPTURED" in result.stdout and os.path.exists(save_path):
            return {
                "result_text": f"📸 스크린샷 저장: {save_path}",
                "files": [save_path],
            }
        return _error_result(f"⚠️ 스크린샷 저장 실패: {result.stderr[:200]}")
    except Exception as e:
        return _error_result(f"❌ 스크린샷 오류: {e}")


# ═══════════════════════════════════════════════════════════════
#  Public API: read_chat
# ═══════════════════════════════════════════════════════════════

def read_chat(
    chat_room: str = "",
    task_dir: str = "",
    send_progress=None,
) -> dict:
    """채팅방 대화 읽기 (클립보드 방식).

    기존 read_kakao_clipboard_direct()와 동일한 전략:
    카카오톡 활성화 → 채팅 영역 클릭 → Ctrl+A → Ctrl+C → Get-Clipboard

    Args:
        chat_room: 대상 채팅방 (빈 문자열이면 현재 열린 방)
        task_dir: 작업 디렉토리
        send_progress: 진행 보고 콜백

    Returns:
        {"result_text": str, "files": list[str]}
    """
    if send_progress is None:
        send_progress = lambda x: None  # noqa: E731

    try:
        _preflight()
    except KakaoNotRunningError as e:
        return _error_result(f"❌ {e}")

    send_progress(f"💬 카카오톡 '{chat_room or '현재 방'}' 읽기 준비 중...")

    # Tier 2 fallback (검증된 PowerShell 방식) 사용
    # 이유: read_kakao_clipboard_direct()가 이미 안정적으로 작동
    try:
        from scripts.telegram.kakao_desktop import read_kakao_clipboard_direct
        return read_kakao_clipboard_direct(
            chat_room=chat_room,
            task_dir=task_dir,
            send_progress=send_progress,
        )
    except Exception as e:
        return _error_result(
            f"❌ 카톡 읽기 오류: {e}\n{traceback.format_exc()[-500:]}"
        )


# ═══════════════════════════════════════════════════════════════
#  Public API: list_rooms
# ═══════════════════════════════════════════════════════════════

def list_rooms(
    task_dir: str = "",
    send_progress=None,
) -> dict:
    """카카오톡 채팅방 목록 조회.

    pywinauto UIA로 채팅방 리스트 패널을 읽거나,
    실패 시 스크린샷으로 대체.

    Returns:
        {"result_text": str, "files": list[str]}
    """
    if send_progress is None:
        send_progress = lambda x: None  # noqa: E731

    try:
        _preflight()
    except KakaoNotRunningError as e:
        return _error_result(f"❌ {e}")

    send_progress("💬 카카오톡 채팅방 목록 조회 중...")

    # 활성화
    if not _activate_kakao():
        return _error_result("❌ 카카오톡 창 활성화 실패. 수동으로 카카오톡을 열어주세요.")

    time.sleep(0.5)

    files = []
    room_names = []

    # Tier 1: pywinauto UIA로 채팅방 리스트 시도
    try:
        _, dlg = _connect_kakao()

        # ChatRoomListView 탐색
        chat_list = None
        try:
            chat_list = dlg.child_window(auto_id='1150')
            if not chat_list.exists(timeout=2):
                chat_list = None
        except Exception:
            pass

        if chat_list:
            # 채팅방 리스트의 자식 항목 읽기
            children = chat_list.children()
            for child in children[:30]:  # 최대 30개
                name = child.window_text().strip()
                if name:
                    room_names.append(name)

    except Exception as exc:
        log.debug(f"pywinauto 채팅방 목록 실패: {exc}")

    # Tier 2: 스크린샷 캡처 (항상 - 보조 자료)
    if task_dir and os.path.isdir(task_dir):
        ss = take_screenshot(task_dir, "kakao_rooms")
        if ss.get("files"):
            files.extend(ss["files"])

    # 결과 구성
    if room_names:
        lines = [f"{i+1}. {name}" for i, name in enumerate(room_names)]
        result_text = (
            f"💬 카카오톡 채팅방 목록 ({len(room_names)}개)\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            + "\n".join(lines)
        )
    else:
        result_text = (
            "💬 카카오톡 채팅방 목록\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "⚠️ 채팅방 목록을 자동으로 읽지 못했습니다.\n"
            "첨부된 스크린샷을 확인해주세요."
        )

    return {"result_text": result_text, "files": files}


# ═══════════════════════════════════════════════════════════════
#  Public API: draft_reply
# ═══════════════════════════════════════════════════════════════

def draft_reply(
    chat_room: str,
    text: str,
    task_dir: str = "",
    send_progress=None,
) -> dict:
    """답장 초안 입력 (Enter 없음 — 2단계 확인 첫 번째 단계).

    카카오톡 활성화 → 입력란 클릭 → 텍스트 입력 (Enter 절대 안 누름)
    → 스크린샷 캡처 → 미리보기 반환.

    Args:
        chat_room: 대상 채팅방
        text: 입력할 텍스트
        task_dir: 작업 디렉토리
        send_progress: 진행 보고 콜백

    Returns:
        {"result_text": str, "files": list[str]}
    """
    if send_progress is None:
        send_progress = lambda x: None  # noqa: E731

    # 입력 검증
    if not chat_room:
        return _error_result(
            "⚠️ 채팅방 이름을 지정해주세요.\n"
            "예: 카톡보내 P5현장 내일 회의 10시입니다"
        )

    if not text:
        return _error_result(
            "⚠️ 보낼 메시지를 입력해주세요.\n"
            "예: 카톡보내 P5현장 내일 회의 10시입니다"
        )

    if len(text) > _MAX_REPLY_LENGTH:
        return _error_result(
            f"⚠️ 메시지가 너무 깁니다 ({len(text)}자).\n"
            f"최대 {_MAX_REPLY_LENGTH}자까지 가능합니다."
        )

    try:
        _preflight()
    except KakaoNotRunningError as e:
        return _error_result(f"❌ {e}")

    send_progress(f"✏️ '{chat_room}' 채팅방에 답장 입력 중...")

    # 1. 활성화
    if not _activate_kakao():
        return _error_result("❌ 카카오톡 창 활성화 실패.")

    time.sleep(0.5)

    # 2. 입력란 찾기 + 텍스트 입력
    typed_ok = False

    # Tier 1: pywinauto UIA로 입력란 직접 제어
    try:
        _, dlg = _connect_kakao()
        edit = _find_edit_box(dlg)

        if edit is not None:
            edit.click_input()
            time.sleep(0.3)

            # 기존 텍스트 클리어
            edit.type_keys('^a', pause=0.1)
            edit.type_keys('{DELETE}', pause=0.1)
            time.sleep(0.2)

            # 한글 입력을 위해 클립보드 paste 방식 사용
            _type_text_via_powershell(text)
            time.sleep(0.3)
            typed_ok = True
    except Exception as exc:
        log.debug(f"pywinauto 입력 실패, fallback: {exc}")

    # Tier 2: PowerShell로 입력
    if not typed_ok:
        try:
            _activate_via_powershell()
            time.sleep(0.3)

            # 입력란 클릭 (카카오톡 창 하단)
            _click_input_area_powershell()
            time.sleep(0.3)

            # 텍스트 입력 (clipboard paste)
            _type_text_via_powershell(text)
            time.sleep(0.3)
            typed_ok = True
        except Exception as exc:
            log.warning(f"PowerShell 입력도 실패: {exc}")

    if not typed_ok:
        return _error_result("❌ 메시지 입력 실패. 카카오톡 채팅방이 열려있는지 확인해주세요.")

    # 3. 스크린샷 캡처
    files = []
    if task_dir and os.path.isdir(task_dir):
        ss = take_screenshot(task_dir, "reply_preview")
        if ss.get("files"):
            files.extend(ss["files"])

    result_text = (
        f"✏️ 카카오톡 답장 초안 입력 완료\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"채팅방: {chat_room}\n"
        f"내용: {text}\n\n"
        f"⚠️ 아직 전송하지 않았습니다.\n"
        f"Enter 키를 누르지 않은 상태입니다."
    )

    return {"result_text": result_text, "files": files}


def _click_input_area_powershell() -> None:
    """PowerShell로 카카오톡 입력란 영역 클릭.

    카카오톡 창 하단의 입력란은 보통 창 높이의 85-90% 위치.
    """
    subprocess.run(
        ["powershell", "-Command",
         "$kakao=Get-Process KakaoTalk -EA SilentlyContinue|Select -First 1;"
         "if(!$kakao){exit 1};"
         "Add-Type @'\n"
         "using System;using System.Runtime.InteropServices;\n"
         "public class KWin{[DllImport(\"user32.dll\")]public static extern bool "
         "GetWindowRect(IntPtr h,out RECT r);}\n"
         "public struct RECT{public int L,T,R,B;}\n"
         "'@\n"
         "$r=New-Object RECT;"
         "[KWin]::GetWindowRect($kakao.MainWindowHandle,[ref]$r)|Out-Null;"
         "$x=[int](($r.L+$r.R)/2);"
         "$y=[int]($r.B-60);"  # 입력란은 하단에서 ~60px 위
         "Add-Type -AssemblyName System.Windows.Forms;"
         "[Cursor]::Position=New-Object Drawing.Point($x,$y);"
         "Start-Sleep -Milliseconds 100;"
         "[System.Windows.Forms.SendKeys]::SendWait(' ');"  # 포커스 전달
         "[System.Windows.Forms.SendKeys]::SendWait('{BACKSPACE}');"],
        capture_output=True, text=True, timeout=_PS_TIMEOUT_SEC,
    )


# ═══════════════════════════════════════════════════════════════
#  Public API: confirm_send
# ═══════════════════════════════════════════════════════════════

def confirm_send(
    task_dir: str = "",
    send_progress=None,
) -> dict:
    """대기 중인 카톡 답장 전송 — Enter 누름.

    이 함수만이 Enter 키를 누르는 것이 허용됨.
    대기 상태(kakao_pending_reply.json)에서 호출됨.

    Returns:
        {"result_text": str, "files": list[str]}
    """
    if send_progress is None:
        send_progress = lambda x: None  # noqa: E731

    try:
        _preflight()
    except KakaoNotRunningError as e:
        return _error_result(f"❌ {e}")

    send_progress("📤 카카오톡 메시지 전송 중...")

    # 1. 활성화
    if not _activate_kakao():
        return _error_result("❌ 카카오톡 창 활성화 실패.")

    time.sleep(0.5)

    # 2. Enter 전송
    enter_sent = False

    # Tier 1: pywinauto
    try:
        _, dlg = _connect_kakao()
        edit = _find_edit_box(dlg)
        if edit is not None:
            # 입력란에 텍스트가 있는지 확인
            try:
                current_text = edit.window_text().strip()
                if not current_text:
                    return _error_result(
                        "⚠️ 입력란이 비어있습니다.\n"
                        "초안이 사라졌습니다. 다시 입력해주세요."
                    )
            except Exception:
                pass  # 텍스트 읽기 실패해도 진행

            edit.click_input()
            time.sleep(0.2)
            edit.type_keys('{ENTER}', pause=0.1)
            enter_sent = True
    except Exception as exc:
        log.debug(f"pywinauto Enter 실패, fallback: {exc}")

    # Tier 2: PowerShell SendKeys
    if not enter_sent:
        try:
            _activate_via_powershell()
            time.sleep(0.3)
            _send_keys_via_powershell('{ENTER}')
            enter_sent = True
        except Exception as exc:
            log.warning(f"PowerShell Enter도 실패: {exc}")

    if not enter_sent:
        return _error_result("❌ 메시지 전송 실패. Enter 키 입력에 실패했습니다.")

    time.sleep(0.5)

    # 3. 전송 확인 스크린샷
    files = []
    if task_dir and os.path.isdir(task_dir):
        ss = take_screenshot(task_dir, "send_confirmed")
        if ss.get("files"):
            files.extend(ss["files"])

    return {
        "result_text": "✅ 메시지 전송 완료!",
        "files": files,
    }


# ═══════════════════════════════════════════════════════════════
#  Public API: cancel_send
# ═══════════════════════════════════════════════════════════════

def cancel_send(
    task_dir: str = "",
    send_progress=None,
) -> dict:
    """대기 중인 카톡 답장 취소 — 입력란 비우기.

    Returns:
        {"result_text": str, "files": list[str]}
    """
    if send_progress is None:
        send_progress = lambda x: None  # noqa: E731

    try:
        _preflight()
    except KakaoNotRunningError as e:
        return _error_result(f"❌ {e}")

    send_progress("❌ 카카오톡 답장 취소 중...")

    # 1. 활성화
    if not _activate_kakao():
        return _error_result("❌ 카카오톡 창 활성화 실패.")

    time.sleep(0.5)

    # 2. 입력란 비우기
    cleared = False

    # Tier 1: pywinauto
    try:
        _, dlg = _connect_kakao()
        edit = _find_edit_box(dlg)
        if edit is not None:
            edit.click_input()
            time.sleep(0.2)
            edit.type_keys('^a', pause=0.1)
            edit.type_keys('{DELETE}', pause=0.1)
            cleared = True
    except Exception as exc:
        log.debug(f"pywinauto 취소 실패, fallback: {exc}")

    # Tier 2: PowerShell
    if not cleared:
        try:
            _activate_via_powershell()
            time.sleep(0.3)
            _send_keys_via_powershell('^a')
            time.sleep(0.1)
            _send_keys_via_powershell('{DEL}')
            cleared = True
        except Exception as exc:
            log.warning(f"PowerShell 취소도 실패: {exc}")

    # ESC도 시도 (입력 모드 해제)
    try:
        _send_keys_via_powershell('{ESC}')
    except Exception:
        pass

    if not cleared:
        return _error_result("❌ 입력란 비우기 실패.")

    return {
        "result_text": "❌ 카톡 답장이 취소되었습니다.\n입력란을 비웠습니다.",
        "files": [],
    }
