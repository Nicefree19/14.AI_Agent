@echo off
echo Launching P5 Agent Dashboard (Obsidian)...
python scripts\launch_dashboard.py
if %ERRORLEVEL% NEQ 0 (
    echo Failed to launch dashboard.
    pause
)
