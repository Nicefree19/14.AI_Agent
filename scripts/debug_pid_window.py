import win32gui
import win32process
import psutil
import os


def get_hwnds_for_pid(pid):
    def callback(hwnd, hwnds):
        if win32gui.IsWindowVisible(hwnd) and win32gui.IsWindowEnabled(hwnd):
            _, found_pid = win32process.GetWindowThreadProcessId(hwnd)
            if found_pid == pid:
                hwnds.append(hwnd)
        return True

    hwnds = []
    win32gui.EnumWindows(callback, hwnds)
    return hwnds


print("Searching for Obsidian processes...")
obsidian_pids = []
for proc in psutil.process_iter(["pid", "name"]):
    if proc.info["name"] == "Obsidian.exe":
        obsidian_pids.append(proc.info["pid"])

print(f"Obsidian PIDs: {obsidian_pids}")

for pid in obsidian_pids:
    hwnds = get_hwnds_for_pid(pid)
    print(f"PID {pid} has windows: {hwnds}")
    for hwnd in hwnds:
        title = win32gui.GetWindowText(hwnd)
        print(f"  - HWND: {hwnd}, Title: '{title}'")

        # Try to restore if minimized
        # import win32con
        # win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        # win32gui.SetForegroundWindow(hwnd)
