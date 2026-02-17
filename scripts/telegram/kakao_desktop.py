#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
카카오톡 PC 앱 유틸리티 모듈
=============================
클립보드 읽기(PowerShell), 답장 대기 상태 관리 등
pywinauto 모듈(kakao_pywinauto.py)의 보조 기능 제공.

핵심 전략:
  카카오톡 공식 API 없음 → 클립보드 우회
  Ctrl+A → Ctrl+C → PowerShell Get-Clipboard → 텍스트 추출
  기존 kakao_utils._parse_pc_format()이 동일 포맷을 파싱 가능.

보안:
  - Enter 키 절대 자동 입력 금지 (2단계 확인 필수)
  - 메시지/채팅방 삭제 금지
  - 파일 전송 금지 (텍스트만)
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
#  상수
# ═══════════════════════════════════════════════════════════════

_BASE_DIR = Path(__file__).resolve().parent.parent.parent
_TELEGRAM_DATA = _BASE_DIR / "telegram_data"
_PENDING_REPLY_FILE = _TELEGRAM_DATA / "kakao_pending_reply.json"

# 중앙화된 설정 (config.py에서 가져옴)
from scripts.telegram.config import (  # noqa: E402
    PENDING_REPLY_TIMEOUT_MIN,
    KAKAO_PS_TIMEOUT_SEC as _PS_TIMEOUT_SEC,
)


# ═══════════════════════════════════════════════════════════════
#  프리플라이트 체크
# ═══════════════════════════════════════════════════════════════

def _verify_kakaotalk_running() -> bool:
    """PowerShell로 KakaoTalk.exe 프로세스 존재 여부 확인.

    Git Bash 호환: tasklist /FI 플래그가 Git Bash에서 경로로 해석되므로
    PowerShell Get-Process를 사용.

    feature flag "kakao_preflight" 가드:
      OFF → fail-open (확인 실패 시 True 반환 — 차단보다 시도가 나음)
      ON  → fail-closed (확인 실패 시 False 반환)
    """
    from scripts.telegram.config import is_enabled

    try:
        result = subprocess.run(
            ["powershell", "-Command",
             "if(Get-Process KakaoTalk -ErrorAction SilentlyContinue){'RUNNING'}else{'NOT_RUNNING'}"],
            capture_output=True, text=True, timeout=_PS_TIMEOUT_SEC,
        )
        return "NOT_RUNNING" not in result.stdout and "RUNNING" in result.stdout
    except Exception as exc:
        if is_enabled("kakao_preflight"):
            log.warning(f"KakaoTalk 프로세스 확인 실패 (fail-closed): {exc}")
            return False  # flag ON: 확인 불가 → 차단
        log.warning(f"KakaoTalk 프로세스 확인 실패 (fail-open): {exc}")
        return True  # flag OFF: 확인 불가 → 차단하지 않음


# ═══════════════════════════════════════════════════════════════
#  직접 클립보드 읽기 (단일 PowerShell 호출)
# ═══════════════════════════════════════════════════════════════

def read_kakao_clipboard_direct(
    chat_room: str = "",
    task_dir: str = "",
    send_progress=None,
) -> dict:
    """단일 PowerShell 스크립트로 카카오톡 채팅을 읽어 클립보드로 가져오기.

    모든 작업을 단일 PowerShell 스크립트에서 수행:
      - 분리 프로세스(Start-Process -WindowStyle Hidden)로 실행
      - 2초 대기 후 KakaoTalk 활성화 → 클릭 → Ctrl+A → Ctrl+C
      - 결과를 파일로 저장 → Python에서 읽기

    Args:
        chat_room: 대상 채팅방 이름 (빈 문자열이면 현재 열린 방)
        task_dir: 작업 디렉토리
        send_progress: 진행 보고 콜백

    Returns:
        {"result_text": str, "files": list[str]}
    """
    if send_progress is None:
        send_progress = lambda x: None  # noqa: E731

    if not _verify_kakaotalk_running():
        return {
            "result_text": (
                "❌ 카카오톡 PC 앱이 실행되지 않았습니다.\n"
                "카카오톡을 먼저 실행한 후 다시 시도해주세요."
            ),
            "files": [],
        }

    import tempfile
    import time

    send_progress(f"💬 카카오톡 '{chat_room or '현재 방'}' 클립보드 읽기 준비 중...")

    # 출력 파일 경로
    output_file = os.path.join(tempfile.gettempdir(), "kakao_clipboard_result.txt")
    if os.path.exists(output_file):
        os.remove(output_file)

    # 클립보드 저장 파일
    clip_file = ""
    if task_dir and os.path.isdir(task_dir):
        clip_file = os.path.join(task_dir, "kakao_clipboard.txt")

    # 단일 PowerShell 스크립트 생성
    script_path = os.path.join(tempfile.gettempdir(), "kakao_read_direct.ps1")
    script = _build_direct_read_script(chat_room, output_file, clip_file)

    with open(script_path, "w", encoding="utf-8-sig") as f:
        f.write(script)

    try:
        # 분리 프로세스로 실행 (Hidden 모드 → 포커스 미탈취)
        subprocess.Popen(
            [
                "powershell.exe",
                "-ExecutionPolicy", "Bypass",
                "-WindowStyle", "Hidden",
                "-File", script_path,
            ],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

        send_progress("💬 카카오톡 클립보드 읽기 진행 중 (5초 대기)...")

        # 스크립트 완료 대기 (최대 15초)
        for i in range(30):
            time.sleep(0.5)
            if os.path.exists(output_file):
                # 파일이 완전히 쓰였는지 확인 (마커 체크)
                try:
                    content = Path(output_file).read_text(encoding="utf-8-sig")
                    if "=== DONE ===" in content:
                        break
                except Exception:
                    pass

        if not os.path.exists(output_file):
            return {
                "result_text": "⏰ 카카오톡 클립보드 읽기 시간 초과 (15초).",
                "files": [],
            }

        content = Path(output_file).read_text(encoding="utf-8-sig")

        # 결과 파싱
        if "ERROR:" in content:
            return {
                "result_text": f"❌ 카카오톡 읽기 오류:\n{content}",
                "files": [],
            }

        # 클립보드 내용 추출
        clip_start = content.find("=== CLIPBOARD ===")
        clip_end = content.find("=== DONE ===")
        if clip_start >= 0 and clip_end >= 0:
            clipboard_text = content[clip_start + len("=== CLIPBOARD ==="):clip_end].strip()
        else:
            clipboard_text = content

        if not clipboard_text or clipboard_text == "EMPTY":
            return {
                "result_text": (
                    "⚠️ 카카오톡 클립보드가 비어있습니다.\n"
                    "채팅방이 열려있고 메시지가 있는지 확인해주세요."
                ),
                "files": [],
            }

        # 파일 목록
        files = []
        if clip_file and os.path.exists(clip_file):
            files.append(clip_file)

        lines = clipboard_text.split("\n")
        result_text = (
            f"💬 카카오톡 클립보드 읽기 완료\n"
            f"채팅방: {chat_room or '현재 열린 방'}\n"
            f"총 {len(lines)}줄\n\n"
            f"{clipboard_text[:3500]}"
        )
        if len(clipboard_text) > 3500:
            result_text += f"\n...(총 {len(clipboard_text)}자, 파일에 전체 저장됨)"

        return {
            "result_text": result_text,
            "files": files,
        }

    except Exception as e:
        return {
            "result_text": f"❌ 카카오톡 직접 읽기 오류: {e}\n{traceback.format_exc()[-500:]}",
            "files": [],
        }


def _build_direct_read_script(
    chat_room: str, output_file: str, clip_file: str
) -> str:
    """카카오톡 클립보드 읽기용 PowerShell 스크립트 생성.

    모든 작업을 단일 프로세스에서 수행:
      1. 2초 대기 (호출자 PowerShell이 종료될 시간)
      2. cmd 창 최소화
      3. KakaoTalk 활성화 (Alt 키 트릭 + SetForegroundWindow)
      4. 채팅 영역 클릭
      5. Ctrl+A → Ctrl+C
      6. Get-Clipboard → 파일 저장
    """
    # 경로의 백슬래시를 이스케이프
    out_escaped = output_file.replace("\\", "\\\\")
    clip_escaped = clip_file.replace("\\", "\\\\") if clip_file else ""

    return f'''
# kakao_read_direct.ps1 — 단일 프로세스 카카오톡 클립보드 읽기
# 생성: kakao_desktop.py._build_direct_read_script()

$ErrorActionPreference = "Continue"
$outputFile = "{out_escaped}"
$clipFile = "{clip_escaped}"

try {{
    # P/Invoke 선언
    Add-Type @"
using System;
using System.Runtime.InteropServices;
public class KakaoWin {{
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
    [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr h);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern void keybd_event(byte vk, byte scan, uint flags, UIntPtr extra);
    [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int cx, int cy, uint f);
    [DllImport("user32.dll")] public static extern void mouse_event(int f, int dx, int dy, int d, int e);
    [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint attach, uint to, bool fAttach);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
}}
"@
    Add-Type -AssemblyName System.Windows.Forms

    # 1. 대기 — 호출자 프로세스(MCP PowerShell)가 종료될 시간
    Start-Sleep -Seconds 2

    # 2. 모든 cmd 창 최소화
    Get-Process cmd -ErrorAction SilentlyContinue | ForEach-Object {{
        [KakaoWin]::ShowWindow($_.MainWindowHandle, 6) | Out-Null
    }}
    Start-Sleep -Milliseconds 300

    # 3. KakaoTalk 활성화
    $kakao = Get-Process KakaoTalk -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $kakao) {{
        "ERROR: KakaoTalk not running" | Out-File $outputFile -Encoding UTF8
        exit 1
    }}
    $h = $kakao.MainWindowHandle

    # Alt 키 트릭으로 foreground lock 해제
    [KakaoWin]::keybd_event(0x12, 0, 0, [UIntPtr]::Zero)
    Start-Sleep -Milliseconds 50
    [KakaoWin]::keybd_event(0x12, 0, 2, [UIntPtr]::Zero)
    Start-Sleep -Milliseconds 100

    # SetForegroundWindow
    [KakaoWin]::ShowWindow($h, 9) | Out-Null  # SW_RESTORE
    [KakaoWin]::SetForegroundWindow($h) | Out-Null
    [KakaoWin]::BringWindowToTop($h) | Out-Null
    Start-Sleep -Milliseconds 500

    # TOPMOST로 설정 (확실하게)
    [KakaoWin]::SetWindowPos($h, [IntPtr](-1), 0, 0, 0, 0, 0x0003) | Out-Null
    Start-Sleep -Milliseconds 300

    # WScript.Shell AppActivate (추가 안전장치)
    $wsh = New-Object -ComObject WScript.Shell
    $wsh.AppActivate($kakao.Id) | Out-Null
    Start-Sleep -Milliseconds 500

    # 4. 포커스 확인
    $fg = [KakaoWin]::GetForegroundWindow()
    $focusOK = ($fg -eq $h)

    # 5. 카카오톡 창 위치 동적 감지 → 채팅 영역 클릭
    Add-Type @"
using System;
using System.Runtime.InteropServices;
public struct RECT2 {{ public int Left, Top, Right, Bottom; }}
public class WinRect2 {{
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT2 r);
}}
"@
    $wr = New-Object RECT2
    [WinRect2]::GetWindowRect($h, [ref]$wr) | Out-Null

    # 채팅 메시지 영역: 카카오톡 창의 왼쪽 절반, 세로 중앙
    # 카카오톡은 [왼쪽: 친구/채팅 목록] [중앙: 대화 내용] [오른쪽: 채팅방 목록] 구조
    $chatX = [int](($wr.Left + $wr.Right) / 2) - 100
    $chatY = [int](($wr.Top + $wr.Bottom) / 2)

    [System.Windows.Forms.Cursor]::Position = New-Object System.Drawing.Point($chatX, $chatY)
    Start-Sleep -Milliseconds 200
    [KakaoWin]::mouse_event(0x0002, 0, 0, 0, 0)  # LEFT DOWN
    [KakaoWin]::mouse_event(0x0004, 0, 0, 0, 0)  # LEFT UP
    Start-Sleep -Milliseconds 500

    # 6. Ctrl+A (전체 선택)
    $wsh.SendKeys('^a')
    Start-Sleep -Milliseconds 300

    # 7. Ctrl+C (복사)
    $wsh.SendKeys('^c')
    Start-Sleep -Milliseconds 500

    # 8. 클립보드 읽기
    $clip = Get-Clipboard -Format Text -ErrorAction SilentlyContinue

    # 9. TOPMOST 해제
    [KakaoWin]::SetWindowPos($h, [IntPtr](-2), 0, 0, 0, 0, 0x0003) | Out-Null

    # 10. 결과 저장
    $result = "Focus=$focusOK, FG=$fg, KakaoTalk=$h`n"
    if ($clip) {{
        $result += "=== CLIPBOARD ===`n"
        $result += $clip
        $result += "`n=== DONE ==="

        # 클립보드 파일도 저장
        if ($clipFile) {{
            $clip | Out-File -FilePath $clipFile -Encoding UTF8 -Force
        }}
    }} else {{
        $result += "=== CLIPBOARD ===`nEMPTY`n=== DONE ==="
    }}

    $result | Out-File -FilePath $outputFile -Encoding UTF8 -Force

}} catch {{
    "ERROR: $($_.Exception.Message)" | Out-File $outputFile -Encoding UTF8 -Force
}}
'''


# ═══════════════════════════════════════════════════════════════
#  답장 대기 상태 관리
# ═══════════════════════════════════════════════════════════════

def save_pending_reply(
    chat_room: str,
    reply_text: str,
    chat_id: int,
    task_dir: str,
) -> None:
    """답장 대기 상태 저장."""
    now = datetime.now()
    data = {
        "chat_room": chat_room,
        "reply_text": reply_text,
        "status": "pending_confirmation",
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=PENDING_REPLY_TIMEOUT_MIN)).isoformat(),
        "chat_id": chat_id,
        "task_dir": task_dir,
    }
    _PENDING_REPLY_FILE.parent.mkdir(parents=True, exist_ok=True)
    # 원자적 쓰기: tmp → replace
    tmp = _PENDING_REPLY_FILE.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    tmp.replace(_PENDING_REPLY_FILE)
    log.info(f"Pending reply saved: {chat_room} → {reply_text[:50]}")


def load_pending_reply() -> Optional[dict]:
    """답장 대기 상태 로드. 만료 시 자동 삭제."""
    if not _PENDING_REPLY_FILE.exists():
        return None
    try:
        data = json.loads(_PENDING_REPLY_FILE.read_text(encoding="utf-8"))
        expires = datetime.fromisoformat(data.get("expires_at", ""))
        if datetime.now() > expires:
            log.info("Pending reply expired, removing.")
            clear_pending_reply()
            return None
        return data
    except Exception as e:
        log.warning(f"Failed to load pending reply: {e}")
        return None


def clear_pending_reply() -> None:
    """답장 대기 상태 삭제."""
    if _PENDING_REPLY_FILE.exists():
        _PENDING_REPLY_FILE.unlink(missing_ok=True)
        log.info("Pending reply cleared.")


def has_pending_reply() -> bool:
    """답장 대기 중인지 확인 (만료 검사 포함)."""
    return load_pending_reply() is not None
