import sys
import os

sys.path.append(os.path.join(os.getcwd(), "scripts"))
from window_controller import WindowController
import time
import pygetwindow as gw

ctrl = WindowController()
print("Launching notepad...")
ctrl.open_app("notepad.exe", "메모장", timeout=5)

print("--- Visible Windows matching '메모장' ---")
wins = gw.getWindowsWithTitle("메모장")
for w in wins:
    print(f"Found: {w.title}")

print("--- All Titles ---")
for t in gw.getAllTitles():
    if t.strip():
        print(f"'{t}'")
