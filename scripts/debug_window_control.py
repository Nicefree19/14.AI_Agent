import sys
import os

print(f"Python Executable: {sys.executable}")
print(f"Working Directory: {os.getcwd()}")

try:
    import pyautogui

    print("SUCCESS: pyautogui imported")
except ImportError as e:
    print(f"ERROR: pyautogui import failed: {e}")

try:
    import pygetwindow as gw

    print("SUCCESS: pygetwindow imported")
    print("--- Visible Windows ---")
    for title in gw.getAllTitles():
        if title.strip():
            print(f"'{title}'")
    print("-----------------------")
except ImportError as e:
    print(f"ERROR: pygetwindow import failed: {e}")

try:
    import cv2

    print("SUCCESS: opencv-python imported")
except ImportError as e:
    print(f"ERROR: opencv-python import failed: {e}")
