@echo off
chcp 65001 >nul
echo ============================================================
echo   🤖 Intelligent Drive-to-Obsidian Sync Watchdog
echo ============================================================
echo.
echo   감시: G:\내 드라이브\appsheet\data\복합동이슈관리대장
echo   저장: ResearchVault\P5-Project\01-Issues
echo   노트북: P5 프로젝트
echo.
echo   Ctrl+C로 종료
echo ============================================================
echo.

cd /d "D:\00.Work_AI_Tool\14.AI_Agent"
call .agent_venv\Scripts\activate.bat

python scripts\intelligent_watchdog.py

pause
