#!/usr/bin/env python3
"""카카오톡 직접 읽기 v2 — ctypes SetForegroundWindow + pyautogui."""
import os
import sys
import time
import ctypes
import ctypes.wintypes
import subprocess

# Force UTF-8
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import pyautogui
import pyperclip

# Disable pyautogui pause for speed
pyautogui.PAUSE = 0

# Win32 API
user32 = ctypes.windll.user32

class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

def get_kakao_hwnd():
    """Get KakaoTalk main window handle via PowerShell."""
    r = subprocess.run(
        ["powershell", "-Command",
         "(Get-Process KakaoTalk -EA SilentlyContinue|Select -First 1).MainWindowHandle"],
        capture_output=True, text=True, timeout=5,
    )
    h = r.stdout.strip()
    return int(h) if h and h != "0" else None

def main():
    hwnd = get_kakao_hwnd()
    if not hwnd:
        print("ERROR: KakaoTalk not running")
        return

    print(f"KakaoTalk hwnd: {hwnd}")

    # Get window rect
    rect = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    print(f"Window: ({rect.left},{rect.top})-({rect.right},{rect.bottom})")

    # Step 1: Minimize cmd windows
    # Use AllowSetForegroundWindow to allow this process
    user32.AllowSetForegroundWindow(-1)  # ASFW_ANY

    # Step 2: Alt key trick + SetForegroundWindow
    VK_MENU = 0x12
    KEYEVENTF_KEYUP = 0x0002
    user32.keybd_event(VK_MENU, 0, 0, 0)
    time.sleep(0.05)
    user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
    time.sleep(0.1)

    # ShowWindow SW_RESTORE then SetForegroundWindow
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    result = user32.SetForegroundWindow(hwnd)
    print(f"SetForegroundWindow: {result}")
    time.sleep(0.5)

    # Check
    fg = user32.GetForegroundWindow()
    print(f"Foreground: {fg}, Match: {fg == hwnd}")

    # Step 3: Clear clipboard
    pyperclip.copy("")

    # Step 4: Calculate chat area and click
    chat_x = (rect.left + rect.right) // 2 - 100
    chat_y = (rect.top + rect.bottom) // 2
    print(f"Clicking chat area: ({chat_x}, {chat_y})")

    pyautogui.click(chat_x, chat_y)
    time.sleep(0.3)

    # Step 5: Ctrl+A, Ctrl+C
    pyautogui.hotkey("ctrl", "a")
    time.sleep(0.2)
    pyautogui.hotkey("ctrl", "c")
    time.sleep(0.5)

    # Step 6: Read clipboard
    clip = pyperclip.paste()
    if clip:
        lines = clip.split("\n")
        print(f"\nClipboard: {len(lines)} lines")
        for line in lines[:10]:
            print(f"  {line[:100]}")
        if len(lines) > 10:
            print(f"  ...(total {len(lines)} lines)")

        if any(k in clip for k in ["오전", "오후", "---", "년"]):
            print("\n>>> KAKAOTALK FORMAT DETECTED!")
        else:
            print("\n>>> Not KakaoTalk format")
    else:
        print("\nClipboard: EMPTY")

        # Try an alternative: maybe we need to click somewhere specific first
        # Let's try clicking the message area more precisely
        # KakaoTalk's message view is typically left of the sidebar
        alt_x = rect.left + 200
        alt_y = (rect.top + rect.bottom) // 2
        print(f"\nRetrying with alt coords ({alt_x}, {alt_y})...")

        # Re-activate
        user32.keybd_event(VK_MENU, 0, 0, 0)
        time.sleep(0.05)
        user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.3)

        pyautogui.click(alt_x, alt_y)
        time.sleep(0.3)
        pyautogui.hotkey("ctrl", "a")
        time.sleep(0.2)
        pyautogui.hotkey("ctrl", "c")
        time.sleep(0.5)

        clip2 = pyperclip.paste()
        if clip2:
            lines2 = clip2.split("\n")
            print(f"Retry clipboard: {len(lines2)} lines")
            for line in lines2[:10]:
                print(f"  {line[:100]}")
        else:
            print("Retry clipboard: STILL EMPTY")


if __name__ == "__main__":
    main()
