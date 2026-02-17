import os
import sys
import time
import subprocess
from window_controller import WindowController

# Configure paths
VAULT_PATH = r"D:\00.Work_AI_Tool\14.AI_Agent\ResearchVault"
# Obsidian URI scheme to open a specific vault
# obsidian://open?vault=ResearchVault&file=Dashboard
OBSIDIAN_URI = f"obsidian://open?path={VAULT_PATH}"


def launch_dashboard():
    ctrl = WindowController()

    # Path found via 'where' command
    obsidian_exe = r"C:\Users\user\AppData\Local\Programs\Obsidian\Obsidian.exe"

    print(f"Launching Obsidian Vault: {VAULT_PATH}")
    print(f"Executable: {obsidian_exe}")

    print(f"Launching Obsidian: {obsidian_exe}")

    try:
        # Launching without arguments works reliably to open the last vault.
        # Passing URI as arg caused stability issues on this machine.
        subprocess.Popen([obsidian_exe])

    except Exception as e:
        print(f"Error launching Obsidian: {e}")
        return

    # Wait for Obsidian to open
    time.sleep(5)

    # Try to focus the window
    # Try multiple common title patterns
    target_titles = ["Obsidian", "ResearchVault", "P5-Project"]

    focused = False
    for title in target_titles:
        if ctrl.focus_window(title):
            print(f"Window '{title}' focused.")
            ctrl.maximize_window(title)
            focused = True
            break

    if not focused:
        print("Obsidian launched, but window focus failed. (Window title might vary)")
        print("--- Diagnostic: Visible Windows ---")
        import pygetwindow as gw

        try:
            for w in gw.getAllTitles():
                if w.strip():
                    print(f"'{w}'")
        except Exception as e:
            print(f"Error listing windows: {e}")
        print("-----------------------------------")


if __name__ == "__main__":
    launch_dashboard()
