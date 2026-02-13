@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8

echo ============================================================
echo   NotebookLM 재인증 도구
echo ============================================================
echo.
echo NotebookLM 연동을 위한 인증 토큰을 갱신합니다.
echo 브라우저 창이 열리면 Google 계정으로 로그인해주세요.
echo 로그인이 완료되면 자동으로 창이 닫히거나, 완료 메시지가 표시됩니다.
echo.

cd /d "D:\00.Work_AI_Tool\14.AI_Agent"
call .agent_venv\Scripts\activate.bat

echo 인증 프로세스 시작...
echo ------------------------------------------------------------
notebooklm-mcp-auth
echo ------------------------------------------------------------
echo.
echo 재인증이 완료되었습니다.
echo 이제 p5_daily.bat 또는 nlm_to_obsidian.py를 실행하여 동기화를 진행할 수 있습니다.
echo.
pause
