@echo off
chcp 65001 >nul
echo ========================================
echo   ResearchVault → NotebookLM 동기화
echo ========================================
echo.

cd /d "D:\00.Work_AI_Tool\14.AI_Agent"

:: agent_venv 활성화
call .agent_venv\Scripts\activate.bat

echo 감시 시작... (Ctrl+C로 종료)
echo.
python scripts\watchdog_sync.py

pause
