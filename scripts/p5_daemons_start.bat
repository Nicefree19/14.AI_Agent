@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8

echo ============================================================
echo   P5 Background Daemons - Starting All
echo ============================================================
echo.

cd /d "%~dp0.."

echo [1/3] Message Daemon (Email + Auto-Triage)...
start "P5-MessageDaemon" cmd /k "chcp 65001 >nul && set PYTHONIOENCODING=utf-8 && call .agent_venv\Scripts\activate.bat && python scripts\message_daemon.py start"
echo   Started (separate window)

echo.
echo [2/3] Intelligent Watchdog (Drive Issue Monitor)...
start "P5-Watchdog" cmd /k "chcp 65001 >nul && set PYTHONIOENCODING=utf-8 && call .agent_venv\Scripts\activate.bat && python scripts\intelligent_watchdog.py"
echo   Started (separate window)

echo.
echo [3/3] Telegram Listener (Message Collector)...
start "P5-TelegramListener" cmd /k "chcp 65001 >nul && set PYTHONIOENCODING=utf-8 && call .agent_venv\Scripts\activate.bat && python scripts\telegram\telegram_listener.py"
echo   Started (separate window)

echo.
echo ============================================================
echo   3 daemons started. Press Ctrl+C in each window to stop.
echo ============================================================
