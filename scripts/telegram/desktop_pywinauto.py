#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
데스크톱 제어 pywinauto 직접 실행 모듈
========================================
MCP 의존성 없이 pywinauto/PowerShell로 데스크톱을 직접 제어.
kakao_pywinauto.py 패턴 기반 (3-Tier Fallback).

3-Tier Fallback:
  Tier 1: pywinauto UIA (modern, Korean text support)
  Tier 2: PowerShell Win32 API (검증된 패턴)
  Tier 3: ctypes/subprocess (최후 수단)

보안:
  - 파일 삭제, 레지스트리 수정, 보안 설정 변경 금지
  - 소프트웨어 설치/제거 금지
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
#  앱 이름 매핑 (한국어 → 실행 경로/영어)
# ═══════════════════════════════════════════════════════════════

_APP_LAUNCH_MAP = {
    "크롬": "chrome",
    "chrome": "chrome",
    "구글크롬": "chrome",
    "아웃룩": "outlook",
    "outlook": "outlook",
    "엑셀": "excel",
    "excel": "excel",
    "워드": "winword",
    "word": "winword",
    "파워포인트": "powerpnt",
    "ppt": "powerpnt",
    "메모장": "notepad",
    "notepad": "notepad",
    "탐색기": "explorer",
    "파일탐색기": "explorer",
    "explorer": "explorer",
    "계산기": "calc",
    "작업관리자": "taskmgr",
    "카카오톡": "KakaoTalk",
    "카톡": "KakaoTalk",
    "터미널": "wt",
    "cmd": "cmd",
    "vscode": "code",
}


def _error_result(msg: str) -> dict:
    """표준 에러 결과."""
    return {"result_text": msg, "files": []}


# ═══════════════════════════════════════════════════════════════
#  take_screenshot — PowerShell Screen Capture
# ═══════════════════════════════════════════════════════════════

def take_screenshot(task_dir: str, name: str = "screenshot") -> dict:
    """전체 화면 스크린샷 캡처.

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
                "result_text": f"📸 스크린샷 저장 완료: {save_path}",
                "files": [save_path],
            }
        return _error_result(f"⚠️ 스크린샷 저장 실패: {result.stderr[:200]}")
    except subprocess.TimeoutExpired:
        return _error_result("⚠️ 스크린샷 캡처 시간 초과")
    except Exception as e:
        return _error_result(f"❌ 스크린샷 오류: {e}")


# ═══════════════════════════════════════════════════════════════
#  list_running_apps — Get-Process
# ═══════════════════════════════════════════════════════════════

def list_running_apps() -> dict:
    """실행 중인 앱 목록 조회 (MainWindowTitle 있는 프로세스).

    Returns:
        {"result_text": str, "files": []}
    """
    try:
        result = subprocess.run(
            ["powershell", "-Command",
             "Get-Process | Where-Object {$_.MainWindowTitle -ne ''} | "
             "Select-Object Name,MainWindowTitle | "
             "Format-Table -AutoSize | Out-String -Width 200"],
            capture_output=True, text=True, timeout=10,
        )
        output = result.stdout.strip()
        if not output:
            return _error_result("⚠️ 실행 중인 창을 찾을 수 없습니다.")

        return {
            "result_text": f"🖥️ 실행 중인 프로그램:\n```\n{output}\n```",
            "files": [],
        }
    except subprocess.TimeoutExpired:
        return _error_result("⚠️ 프로세스 목록 조회 시간 초과")
    except Exception as e:
        return _error_result(f"❌ 프로세스 목록 오류: {e}")


# ═══════════════════════════════════════════════════════════════
#  activate_app — pywinauto / PowerShell AppActivate
# ═══════════════════════════════════════════════════════════════

def activate_app(app_name: str) -> dict:
    """앱 창 활성화 (포그라운드 전환).

    Args:
        app_name: 프로세스 이름 또는 창 제목 일부

    Returns:
        {"result_text": str, "files": []}
    """
    # Tier 1: pywinauto
    try:
        from pywinauto import Application
        app = Application(backend='uia').connect(best_match=app_name, timeout=3)
        dlg = app.window(best_match=app_name)
        dlg.set_focus()
        time.sleep(0.3)
        title = dlg.window_text()[:50]
        return {
            "result_text": f"✅ '{title}' 창을 활성화했습니다.",
            "files": [],
        }
    except Exception as exc:
        log.debug(f"pywinauto 활성화 실패: {exc}")

    # Tier 2: PowerShell AppActivate
    try:
        result = subprocess.run(
            ["powershell", "-Command",
             f"$wsh=New-Object -ComObject WScript.Shell;"
             f"$proc=Get-Process -Name '*{app_name}*' -EA SilentlyContinue|Select -First 1;"
             f"if($proc){{$wsh.AppActivate($proc.Id);'OK:'+$proc.Name}}"
             f"else{{"
             f"  $win=Get-Process|Where{{$_.MainWindowTitle -like '*{app_name}*'}}|Select -First 1;"
             f"  if($win){{$wsh.AppActivate($win.Id);'OK:'+$win.Name}}else{{'FAIL'}}"
             f"}}"],
            capture_output=True, text=True, timeout=5,
        )
        if result.stdout.startswith("OK:"):
            proc_name = result.stdout.split(":", 1)[1].strip()
            return {
                "result_text": f"✅ '{proc_name}' 창을 활성화했습니다.",
                "files": [],
            }
    except Exception as exc:
        log.debug(f"PowerShell 활성화 실패: {exc}")

    return _error_result(f"❌ '{app_name}' 프로그램을 찾을 수 없습니다.")


# ═══════════════════════════════════════════════════════════════
#  launch_app — subprocess.Popen
# ═══════════════════════════════════════════════════════════════

def launch_app(app_name: str) -> dict:
    """앱 실행.

    Args:
        app_name: 한국어 또는 영어 앱 이름

    Returns:
        {"result_text": str, "files": []}
    """
    app_key = app_name.lower().strip()
    exe_name = _APP_LAUNCH_MAP.get(app_key, app_key)

    try:
        subprocess.Popen(
            ["start", exe_name],
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(1)
        return {
            "result_text": f"✅ '{app_name}' ({exe_name}) 실행 요청 완료.",
            "files": [],
        }
    except Exception as e:
        return _error_result(f"❌ '{app_name}' 실행 실패: {e}")


# ═══════════════════════════════════════════════════════════════
#  type_text_to_active — 클립보드 paste
# ═══════════════════════════════════════════════════════════════

def type_text_to_active(text: str) -> dict:
    """활성 창에 텍스트 입력 (클립보드 paste 방식).

    Args:
        text: 입력할 텍스트

    Returns:
        {"result_text": str, "files": []}
    """
    if not text:
        return _error_result("⚠️ 입력할 텍스트가 없습니다.")

    try:
        escaped = text.replace("'", "''")
        result = subprocess.run(
            ["powershell", "-Command",
             f"Set-Clipboard -Value '{escaped}';"
             f"Add-Type -AssemblyName System.Windows.Forms;"
             f"[System.Windows.Forms.SendKeys]::SendWait('^v')"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return {
                "result_text": f"⌨️ 텍스트 입력 완료: {text[:50]}{'...' if len(text) > 50 else ''}",
                "files": [],
            }
        return _error_result(f"⚠️ 텍스트 입력 실패: {result.stderr[:200]}")
    except Exception as e:
        return _error_result(f"❌ 텍스트 입력 오류: {e}")


# ═══════════════════════════════════════════════════════════════
#  click_at_coords — pywinauto.mouse / PowerShell
# ═══════════════════════════════════════════════════════════════

def click_at_coords(x: int, y: int) -> dict:
    """좌표 클릭.

    Args:
        x, y: 화면 좌표

    Returns:
        {"result_text": str, "files": []}
    """
    # Tier 1: pywinauto
    try:
        from pywinauto import mouse
        mouse.click(coords=(x, y))
        return {
            "result_text": f"🖱️ ({x}, {y}) 클릭 완료.",
            "files": [],
        }
    except Exception:
        pass

    # Tier 2: PowerShell
    try:
        result = subprocess.run(
            ["powershell", "-Command",
             f"Add-Type -AssemblyName System.Windows.Forms;"
             f"[System.Windows.Forms.Cursor]::Position="
             f"New-Object System.Drawing.Point({x},{y});"
             f"Start-Sleep -Milliseconds 50;"
             # mouse_event for left click
             f"$sig=@'\n"
             f"[DllImport(\"user32.dll\")]public static extern void mouse_event"
             f"(int f,int x,int y,int d,int e);\n"
             f"'@\n"
             f"$m=Add-Type -MemberDefinition $sig -Name WinMouse -Namespace M -PassThru;"
             f"$m::mouse_event(2,0,0,0,0);Start-Sleep -Milliseconds 30;"
             f"$m::mouse_event(4,0,0,0,0)"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return {
                "result_text": f"🖱️ ({x}, {y}) 클릭 완료.",
                "files": [],
            }
    except Exception:
        pass

    return _error_result(f"❌ ({x}, {y}) 클릭 실패.")


# ═══════════════════════════════════════════════════════════════
#  get_system_info — 시스템 정보
# ═══════════════════════════════════════════════════════════════

def get_system_info() -> dict:
    """시스템 정보 조회.

    Returns:
        {"result_text": str, "files": []}
    """
    try:
        result = subprocess.run(
            ["powershell", "-Command",
             "$os=[Environment]::OSVersion.VersionString;"
             "$cpu=(Get-CimInstance Win32_Processor).Name;"
             "$mem=[math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory/1GB,1);"
             "$disk=Get-CimInstance Win32_LogicalDisk -Filter \"DeviceID='C:'\";"
             "$free=[math]::Round($disk.FreeSpace/1GB,1);"
             "$total=[math]::Round($disk.Size/1GB,1);"
             "\"OS: $os`nCPU: $cpu`nRAM: ${mem}GB`nDisk C: ${free}/${total}GB free\""],
            capture_output=True, text=True, timeout=10,
        )
        output = result.stdout.strip()
        if output:
            return {
                "result_text": f"💻 시스템 정보:\n```\n{output}\n```",
                "files": [],
            }
        return _error_result("⚠️ 시스템 정보 조회 실패")
    except Exception as e:
        return _error_result(f"❌ 시스템 정보 오류: {e}")
