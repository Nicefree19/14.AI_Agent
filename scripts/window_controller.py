import pygetwindow as gw
import pyautogui
import time
import os
import subprocess
import logging
from typing import Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


class WindowController:
    """
    A controller class to manage Windows applications and UI interactions.
    Uses pygetwindow for window management and pyautogui for input simulation.
    """

    def __init__(self):
        # Fail-safe: moving mouse to upper-left corner will abort script
        pyautogui.FAILSAFE = True
        # Set a pause between actions
        pyautogui.PAUSE = 0.5

    def find_window(self, title_part: str) -> Optional[gw.Win32Window]:
        """Find a window by a partial title match."""
        windows = gw.getWindowsWithTitle(title_part)
        if windows:
            return windows[0]
        return None

    def open_app(
        self, app_path: str, title_part: str = None, timeout: int = 10
    ) -> bool:
        """
        Open an application given its path.
        If title_part is provided, checks if it's already running first.
        """
        if title_part:
            win = self.find_window(title_part)
            if win:
                logging.info(f"Window '{title_part}' found. Activating...")
                try:
                    if win.isMinimized:
                        win.restore()
                    win.activate()
                    return True
                except Exception as e:
                    logging.warning(f"Failed to activate existing window: {e}")

        logging.info(f"Launching {app_path}...")
        try:
            subprocess.Popen(app_path)
            # Wait for window to appear if title is known
            if title_part:
                start_time = time.time()
                while time.time() - start_time < timeout:
                    win = self.find_window(title_part)
                    if win:
                        logging.info(f"Application launched and window detected.")
                        return True
                    time.sleep(1)
                logging.warning(
                    f"Application launched but window '{title_part}' not found within timeout."
                )
            return True
        except FileNotFoundError:
            logging.error(f"Application not found at {app_path}")
            return False
        except Exception as e:
            logging.error(f"Error launching application: {e}")
            return False

    def focus_window(self, title_part: str) -> bool:
        """Bring a window to the foreground."""
        win = self.find_window(title_part)
        if win:
            try:
                if win.isMinimized:
                    win.restore()
                win.activate()
                return True
            except Exception as e:
                logging.error(f"Could not focus window: {e}")
                return False
        logging.warning(f"Window containing '{title_part}' not found.")
        return False

    def type_text(self, text: str, interval: float = 0.05):
        """Type text into the active window."""
        logging.info(f"Typing text: {text}")
        pyautogui.write(text, interval=interval)

    def press_hotkey(self, *keys):
        """Press a key combination (e.g., 'ctrl', 'c')."""
        logging.info(f"Pressing hotkey: {' + '.join(keys)}")
        pyautogui.hotkey(*keys)

    def click_at(self, x: int, y: int):
        """Click at specific coordinates."""
        pyautogui.click(x, y)

    def maximize_window(self, title_part: str):
        """Maximize the specified window."""
        win = self.find_window(title_part)
        if win:
            if not win.isMaximized:
                win.maximize()


if __name__ == "__main__":
    # Test block
    ctrl = WindowController()
    # Example: Open Notepad
    ctrl.open_app("notepad.exe", "Notepad")
    time.sleep(1)
    ctrl.type_text("Hello from P5 Agent Windows Controller!", interval=0.1)
