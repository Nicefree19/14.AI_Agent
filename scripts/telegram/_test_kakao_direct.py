#!/usr/bin/env python3
"""카카오톡 직접 읽기 테스트 — pyautogui 방식."""
import os
import sys
import time
import ctypes
import ctypes.wintypes
import subprocess

def get_kakao_window_rect():
    """PowerShell로 KakaoTalk 창 위치 조회."""
    r = subprocess.run(
        ["powershell", "-Command",
         "$k=Get-Process KakaoTalk -EA SilentlyContinue|Select -First 1;"
         "if(!$k){exit 1};"
         "Add-Type 'using System;using System.Runtime.InteropServices;"
         "public struct R{public int L,T,Ri,B;}"
         "public class WR{[DllImport(\"user32.dll\")]"
         "public static extern bool GetWindowRect(IntPtr h,out R r);}';"
         "$r=New-Object R;"
         "[WR]::GetWindowRect($k.MainWindowHandle,[ref]$r)|Out-Null;"
         "\"$($r.L),$($r.T),$($r.Ri),$($r.B)\""],
        capture_output=True, text=True, timeout=5,
    )
    if r.returncode != 0:
        return None
    parts = r.stdout.strip().split(",")
    return tuple(int(x) for x in parts)


def main():
    # Force UTF-8
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    try:
        import pyautogui
        import pyperclip
    except ImportError as e:
        print(f"Missing dependency: {e}")
        print("pip install pyautogui pyperclip")
        return

    print("=== KakaoTalk Direct Read Test (pyautogui) ===")

    # 1. Get KakaoTalk window rect
    rect = get_kakao_window_rect()
    if not rect:
        print("ERROR: KakaoTalk not running")
        return
    left, top, right, bottom = rect
    print(f"KakaoTalk window: ({left},{top})-({right},{bottom})")
    print(f"  Size: {right-left} x {bottom-top}")

    # 2. Calculate chat message area center
    # KakaoTalk layout: [sidebar ~70px] [chat content] [room list ~300px]
    chat_x = (left + right) // 2 - 100
    chat_y = (top + bottom) // 2
    print(f"Chat area target: ({chat_x}, {chat_y})")

    # 3. Clear clipboard
    pyperclip.copy("")
    print("Clipboard cleared")

    # 4. Click on KakaoTalk chat area using pyautogui
    print(f"Clicking at ({chat_x}, {chat_y})...")
    pyautogui.click(chat_x, chat_y)
    time.sleep(0.5)

    # 5. Select all + Copy
    print("Sending Ctrl+A...")
    pyautogui.hotkey("ctrl", "a")
    time.sleep(0.3)

    print("Sending Ctrl+C...")
    pyautogui.hotkey("ctrl", "c")
    time.sleep(0.5)

    # 6. Read clipboard
    clip = pyperclip.paste()
    if clip:
        lines = clip.split("\n")
        print(f"\n=== CLIPBOARD: {len(lines)} lines ===")
        for line in lines[:15]:
            print(f"  {line[:100]}")
        if len(lines) > 15:
            print(f"  ...(total {len(lines)} lines)")

        # Check if it looks like KakaoTalk format
        if "오전" in clip or "오후" in clip or "---" in clip:
            print("\n>>> LOOKS LIKE KAKAOTALK FORMAT!")
        else:
            print("\n>>> Does NOT look like KakaoTalk format (might be wrong window)")
    else:
        print("\n=== CLIPBOARD: EMPTY ===")


if __name__ == "__main__":
    main()
