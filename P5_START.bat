@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion
title P5 Agent - One-Click Launcher
color 0A

REM ═══════════════════════════════════════════════════════════
REM  P5 Agent 원클릭 런처
REM  텔레그램으로 외부에서 작업 요청을 받기 위한 모든 서비스를 시작
REM ═══════════════════════════════════════════════════════════

set "PROJECT_DIR=%~dp0"
set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"
set "SCRIPTS_DIR=%PROJECT_DIR%\scripts"
set "VENV_PYTHON=%PROJECT_DIR%\.agent_venv\Scripts\python.exe"
set "VENV_ACTIVATE=%PROJECT_DIR%\.agent_venv\Scripts\activate.bat"
set "ENV_FILE=%PROJECT_DIR%\.env"
set "AUTOEXECUTOR=%SCRIPTS_DIR%\p5_autoexecutor.bat"

for %%I in ("%PROJECT_DIR%") do set "FOLDER_NAME=%%~nxI"
set "TASK_NAME=Claude_P5Agent_%FOLDER_NAME%"

echo.
echo  ╔═══════════════════════════════════════════════════════╗
echo  ║                                                       ║
echo  ║          P5 Agent - 원클릭 런처                       ║
echo  ║          텔레그램 원격 작업 수신 시스템                ║
echo  ║                                                       ║
echo  ╚═══════════════════════════════════════════════════════╝
echo.

REM ─── Phase 1: 사전 점검 ────────────────────────────────────
echo  [점검] 시스템 요구사항 확인 중...
echo.

set "FAIL=0"

REM 1. .env 파일
if exist "%ENV_FILE%" (
    echo    [OK] .env 파일
) else (
    echo    [!!] .env 파일 없음 — 봇 토큰 설정 필요
    set "FAIL=1"
)

REM 2. Python venv
if exist "%VENV_PYTHON%" (
    echo    [OK] Python 가상환경
) else (
    echo    [!!] .agent_venv 없음 — python -m venv .agent_venv 실행 필요
    set "FAIL=1"
)

REM 3. Claude CLI
set "CLAUDE_OK=0"
if exist "%USERPROFILE%\.local\bin\claude.exe" (
    set "CLAUDE_OK=1"
    set "CLAUDE_EXE=%USERPROFILE%\.local\bin\claude.exe"
)
if "!CLAUDE_OK!"=="0" (
    for /f "delims=" %%i in ('where claude.cmd 2^>NUL') do (
        set "CLAUDE_OK=1"
        set "CLAUDE_EXE=%%i"
    )
)
if "!CLAUDE_OK!"=="0" (
    if exist "%APPDATA%\npm\claude.cmd" (
        set "CLAUDE_OK=1"
        set "CLAUDE_EXE=%APPDATA%\npm\claude.cmd"
    )
)
if "!CLAUDE_OK!"=="1" (
    echo    [OK] Claude CLI: !CLAUDE_EXE!
) else (
    echo    [!!] Claude CLI 미설치 — npm i -g @anthropic-ai/claude-code
    set "FAIL=1"
)

REM 4. 핵심 스크립트 존재 확인
if exist "%SCRIPTS_DIR%\telegram\telegram_listener.py" (
    echo    [OK] 텔레그램 리스너
) else (
    echo    [!!] telegram_listener.py 없음
    set "FAIL=1"
)

if exist "%AUTOEXECUTOR%" (
    echo    [OK] 자동 실행기
) else (
    echo    [!!] p5_autoexecutor.bat 없음
    set "FAIL=1"
)

REM 5. .env 내 봇 토큰 검증 (Python)
if exist "%VENV_PYTHON%" if exist "%ENV_FILE%" (
    "%VENV_PYTHON%" -c "from dotenv import load_dotenv; load_dotenv(r'%ENV_FILE%'); import os,sys; t=os.getenv('TELEGRAM_BOT_TOKEN',''); sys.exit(0 if t and t not in ('YOUR_BOT_TOKEN','your_bot_token_here') else 1)" 2>NUL
    if !ERRORLEVEL! EQU 0 (
        echo    [OK] 봇 토큰 설정됨
    ) else (
        echo    [!!] TELEGRAM_BOT_TOKEN 미설정 — .env 파일 수정 필요
        set "FAIL=1"
    )
)

echo.

if "!FAIL!"=="1" (
    echo  ════════════════════════════════════════════════════
    echo   사전 점검 실패! 위 [!!] 항목을 먼저 해결하세요.
    echo  ════════════════════════════════════════════════════
    echo.
    pause
    exit /b 1
)

echo  ════════════════════════════════════════════════════
echo   사전 점검 완료!
echo  ════════════════════════════════════════════════════
echo.

REM ─── Phase 2: 작업 스케줄러 등록/확인 ──────────────────────
echo  [스케줄러] 작업 스케줄러 확인 중...

cmd /c "schtasks /Query /TN "%TASK_NAME%" /FO CSV" >NUL 2>&1
if !ERRORLEVEL! EQU 0 (
    echo    [OK] 스케줄러 이미 등록됨: %TASK_NAME%

    REM 혹시 비활성 상태면 활성화
    cmd /c "schtasks /Change /TN "%TASK_NAME%" /ENABLE" >NUL 2>&1
    echo    [OK] 스케줄러 활성화 확인
) else (
    echo    [--] 스케줄러 미등록 — 자동 등록 시도...

    REM 관리자 권한 확인
    net session >NUL 2>&1
    if !ERRORLEVEL! EQU 0 (
        cmd /c "schtasks /Create /TN "%TASK_NAME%" /TR "\"%AUTOEXECUTOR%\"" /SC MINUTE /MO 1 /RL HIGHEST /IT /F" >NUL 2>&1
        if !ERRORLEVEL! EQU 0 (
            echo    [OK] 스케줄러 등록 완료 ^(매 1분^)
        ) else (
            echo    [!!] 등록 실패 — 수동 등록: scripts\register_scheduler.bat ^(관리자^)
        )
    ) else (
        echo    [!!] 관리자 권한 필요 — 스케줄러 수동 등록:
        echo         scripts\register_scheduler.bat 우클릭 → 관리자 실행
        echo.
        echo    스케줄러 없이도 시작합니다. ^(텔레그램 리스너만 작동^)
    )
)

echo.

REM ─── Phase 3: 기존 프로세스 정리 ───────────────────────────
echo  [정리] 기존 프로세스 확인...

REM 이미 실행 중인 리스너 확인
"%VENV_PYTHON%" -c "
import os, sys
pid_file = r'%PROJECT_DIR%\telegram_data\listener.pid'
if not os.path.exists(pid_file):
    sys.exit(0)
try:
    pid = int(open(pid_file).read().strip())
    import ctypes
    h = ctypes.windll.kernel32.OpenProcess(0x00100000, False, pid)
    if h:
        ctypes.windll.kernel32.CloseHandle(h)
        print(f'    [--] 리스너 이미 실행 중 (PID={pid})')
        sys.exit(1)
    else:
        os.remove(pid_file)
        print('    [OK] 오래된 PID 파일 정리')
        sys.exit(0)
except:
    sys.exit(0)
" 2>NUL
set "LISTENER_RUNNING=!ERRORLEVEL!"

REM 오래된 잠금 파일 정리
if exist "%PROJECT_DIR%\scripts\p5_autoexecutor.lock" (
    del "%PROJECT_DIR%\scripts\p5_autoexecutor.lock" 2>NUL
    echo    [OK] 오래된 잠금 파일 정리
)

echo.

REM ─── Phase 4: 서비스 시작 ──────────────────────────────────
echo  [시작] 서비스 시작 중...
echo.

cd /d "%PROJECT_DIR%"

REM 1. 텔레그램 리스너 (핵심 — 메시지 수집)
if "!LISTENER_RUNNING!"=="1" (
    echo    [1] 텔레그램 리스너: 이미 실행 중 — 건너뜀
) else (
    start "P5-TelegramListener" /MIN cmd /k "title P5 - Telegram Listener && chcp 65001 >nul && set PYTHONIOENCODING=utf-8 && cd /d "%PROJECT_DIR%" && call "%VENV_ACTIVATE%" && python scripts\telegram\telegram_listener.py"
    echo    [1] 텔레그램 리스너: 시작됨 ^(최소화 창^)
)

echo.

REM ─── Phase 5: 최종 상태 표시 ───────────────────────────────
echo.
echo  ╔═══════════════════════════════════════════════════════╗
echo  ║                                                       ║
echo  ║   P5 Agent 시작 완료!                                 ║
echo  ║                                                       ║
echo  ║   텔레그램으로 메시지를 보내면 자동 처리됩니다.       ║
echo  ║                                                       ║
echo  ╠═══════════════════════════════════════════════════════╣
echo  ║                                                       ║
echo  ║   [텔레그램 리스너]  10초마다 메시지 수집             ║
echo  ║   [작업 스케줄러]    1분마다 Claude Code 실행         ║
echo  ║                                                       ║
echo  ╠═══════════════════════════════════════════════════════╣
echo  ║                                                       ║
echo  ║   관리 명령:                                          ║
echo  ║   - 중지: 이 창을 닫고 리스너 창도 닫기              ║
echo  ║   - 스케줄러 중지:                                    ║
echo  ║     schtasks /Change /TN "%TASK_NAME%" /DISABLE       ║
echo  ║   - 로그 확인:                                        ║
echo  ║     scripts\p5_autoexecutor.log                       ║
echo  ║                                                       ║
echo  ╚═══════════════════════════════════════════════════════╝
echo.

REM ─── 대기 루프: 상태 모니터링 ──────────────────────────────
echo  상태 모니터링 중... (이 창을 닫으면 모니터링만 중지됩니다)
echo  리스너는 별도 창에서 계속 실행됩니다.
echo.

:MONITOR_LOOP
    REM 10초마다 간단 상태 표시
    timeout /t 30 /nobreak >nul

    REM 리스너 생존 확인
    set "L_STATUS=중지됨"
    if exist "%PROJECT_DIR%\telegram_data\listener.pid" (
        "%VENV_PYTHON%" -c "
import os, sys, ctypes
try:
    pid = int(open(r'%PROJECT_DIR%\telegram_data\listener.pid').read().strip())
    h = ctypes.windll.kernel32.OpenProcess(0x00100000, False, pid)
    if h:
        ctypes.windll.kernel32.CloseHandle(h)
        sys.exit(0)
except: pass
sys.exit(1)
" 2>NUL
        if !ERRORLEVEL! EQU 0 set "L_STATUS=실행 중"
    )

    REM 잠금 상태 확인
    set "W_STATUS=대기 중"
    if exist "%PROJECT_DIR%\telegram_data\working.json" set "W_STATUS=작업 중"

    REM 시각
    for /f "tokens=1-2 delims= " %%a in ("%time%") do set "NOW=%%a"

    echo  [!NOW!] 리스너: !L_STATUS! ^| 작업: !W_STATUS!
goto MONITOR_LOOP
