@echo off
chcp 65001 >nul
echo ============================================================
echo   P5 Task Scheduler 자동 등록
echo   (관리자 권한으로 실행 필요)
echo ============================================================
echo.

:: 일일 배치: 매일 08:30 자동 실행
echo [1/3] P5_Daily 등록 (매일 08:30)...
schtasks /create /tn "P5_Daily" /tr "D:\00.Work_AI_Tool\14.AI_Agent\scripts\p5_daily.bat" /sc daily /st 08:30 /f
if %errorlevel%==0 (echo   ✅ 등록 성공) else (echo   ❌ 등록 실패 - 관리자 권한 확인)
echo.

:: 주간 배치: 매주 월요일 08:00
echo [2/3] P5_Weekly 등록 (매주 월요일 08:00)...
schtasks /create /tn "P5_Weekly" /tr "D:\00.Work_AI_Tool\14.AI_Agent\scripts\p5_weekly.bat" /sc weekly /d MON /st 08:00 /f
if %errorlevel%==0 (echo   ✅ 등록 성공) else (echo   ❌ 등록 실패 - 관리자 권한 확인)
echo.

:: 데몬 자동 기동: 로그온 시
echo [3/3] P5_Daemons 등록 (로그온 시 자동 시작)...
schtasks /create /tn "P5_Daemons" /tr "D:\00.Work_AI_Tool\14.AI_Agent\scripts\p5_daemons_start.bat" /sc onlogon /f
if %errorlevel%==0 (echo   ✅ 등록 성공) else (echo   ❌ 등록 실패 - 관리자 권한 확인)
echo.

echo ============================================================
echo   등록 상태 확인
echo ============================================================
schtasks /query /tn "P5_Daily" /fo table 2>nul
schtasks /query /tn "P5_Weekly" /fo table 2>nul
schtasks /query /tn "P5_Daemons" /fo table 2>nul
echo.
pause
