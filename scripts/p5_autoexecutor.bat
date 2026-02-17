@echo off
setlocal EnableExtensions EnableDelayedExpansion
set "PYTHONIOENCODING=utf-8"

REM =============================================
REM  P5 Agent - Claude Code Auto Executor
REM  Telegram message check + Claude Code launch
REM =============================================

set "BASE=%~dp0"
set "ROOT=%BASE%.."
set "SPF=%ROOT%\CLAUDE.md"
set "LOG=%BASE%p5_autoexecutor.log"
set "LOCKFILE=%BASE%p5_autoexecutor.lock"
set "VENV_PYTHON=%ROOT%\.agent_venv\Scripts\python.exe"
set "QUICK_CHECK=%BASE%telegram\quick_check.py"
set "PYTHON_RUNNER=%BASE%telegram\python_runner.py"
set "CLAUDE_EXECUTOR=%BASE%telegram\claude_executor.py"
set "MAX_RUNTIME_SEC=1800"

REM --- Log Rotation (1MB limit) ---
if exist "%LOG%" (
    for %%F in ("%LOG%") do if %%~zF GTR 1048576 (
        if exist "%LOG%.bak" del "%LOG%.bak"
        move "%LOG%" "%LOG%.bak" >NUL 2>&1
    )
)

REM --- VENV Validation ---
if not exist "%VENV_PYTHON%" (
    echo [%date% %time%] [ERROR] VENV not found: %VENV_PYTHON%>> "%LOG%"
    exit /b 97
)

REM --- Detect Claude CLI ---
set "CLAUDE_EXE="

REM 1. Check user local bin
if exist "%USERPROFILE%\.local\bin\claude.exe" (
    set "CLAUDE_EXE=%USERPROFILE%\.local\bin\claude.exe"
    goto CLAUDE_FOUND
)

REM 2. Check npm global
for /f "delims=" %%i in ('where claude.cmd 2^>NUL') do (
    set "CLAUDE_EXE=%%i"
    goto CLAUDE_FOUND
)

REM 3. Check npm local
if exist "%APPDATA%\npm\claude.cmd" (
    set "CLAUDE_EXE=%APPDATA%\npm\claude.cmd"
    goto CLAUDE_FOUND
)

REM 4. Not found
echo [%date% %time%] [ERROR] Claude CLI not found>> "%LOG%"
exit /b 99

:CLAUDE_FOUND

REM --- Daily Cleanup (1일 1회, non-blocking) ---
set "CLEANUP_MARKER=%BASE%cleanup_last_run.txt"
if not exist "%CLEANUP_MARKER%" goto :DO_CLEANUP
"%VENV_PYTHON%" -c "import os,sys,time; sys.exit(0 if time.time()-os.path.getmtime(sys.argv[1])>86400 else 1)" "%CLEANUP_MARKER%" 2>NUL
if !ERRORLEVEL! EQU 0 goto :DO_CLEANUP
goto :SKIP_CLEANUP

:DO_CLEANUP
echo [%date% %time%] [CLEANUP] Running daily cleanup...>> "%LOG%"
"%VENV_PYTHON%" -m scripts.telegram.cleanup_manager --days 30 >> "%LOG%" 2>&1
echo %date% %time%> "%CLEANUP_MARKER%"
echo [%date% %time%] [CLEANUP] Done.>> "%LOG%"

:SKIP_CLEANUP

REM ============================================
REM  GUARD: Lock file based (NOT tasklist)
REM  - Only prevents multiple autoexecutors
REM  - Does NOT block on user's interactive CLI
REM  - Self-heals via stale detection (>30 min)
REM ============================================
if exist "%LOCKFILE%" (
    REM Check lock file age using Python (> MAX_RUNTIME_SEC = stale)
    "%VENV_PYTHON%" -c "import os,sys,time; age=time.time()-os.path.getmtime(sys.argv[1]); sys.exit(0 if age>float(sys.argv[2]) else 1)" "%LOCKFILE%" "%MAX_RUNTIME_SEC%" 2>NUL
    if !ERRORLEVEL! EQU 0 (
        REM Stale lock detected. Read stored PID and kill if still alive.
        set "STALE_PID="
        for /f "usebackq tokens=2 delims==" %%P in ("%LOCKFILE%") do (
            if not defined STALE_PID set "STALE_PID=%%P"
        )
        if defined STALE_PID (
            tasklist /FI "PID eq !STALE_PID!" /FO CSV 2>NUL | findstr /R "^\"" >NUL 2>&1
            if !ERRORLEVEL! EQU 0 (
                taskkill /PID !STALE_PID! /T /F >NUL 2>&1
                echo [%date% %time%] [WARN] Killed stale process PID=!STALE_PID!>> "%LOG%"
            )
        )
        del "%LOCKFILE%" 2>NUL
        echo [%date% %time%] [WARN] Stale lock removed (age exceeds %MAX_RUNTIME_SEC%s^)>> "%LOG%"
    ) else (
        REM Lock is fresh. Another autoexecutor is running. Skip.
        echo [%date% %time%] [SKIP] Autoexecutor lock active>> "%LOG%"
        exit /b 98
    )
)

echo [%date% %time%] [START] Claude CLI: %CLAUDE_EXE%>> "%LOG%"

REM --- Step 1: Quick check (message + lock state) ---
"%VENV_PYTHON%" "%QUICK_CHECK%" 2>>"%LOG%"
set CHECK_RESULT=!ERRORLEVEL!

if !CHECK_RESULT! EQU 0 (
    echo [%date% %time%] [NO_MESSAGE] No new messages.>> "%LOG%"
    exit /b 0
)
if !CHECK_RESULT! EQU 2 (
    echo [%date% %time%] [LOCKED] Another task in progress.>> "%LOG%"
    exit /b 98
)
if !CHECK_RESULT! EQU 3 (
    echo [%date% %time%] [ERROR] Check failed. Will retry.>> "%LOG%"
    exit /b 0
)

REM CHECK_RESULT=1: New messages found

REM --- Step 2: Python Direct Runner (keyword-matched skills → 0 LLM tokens) ---
echo [%date% %time%] [PYTHON_RUNNER] Attempting direct skill execution...>> "%LOG%"
"%VENV_PYTHON%" "%PYTHON_RUNNER%" 2>>"%LOG%"
set RUNNER_RESULT=!ERRORLEVEL!

if !RUNNER_RESULT! EQU 0 (
    echo [%date% %time%] [PYTHON_RUNNER] Direct skill completed. No Claude Code needed.>> "%LOG%"
    echo.>> "%LOG%"
    exit /b 0
)
if !RUNNER_RESULT! EQU 2 (
    echo [%date% %time%] [PYTHON_RUNNER] No messages or locked. Skipping.>> "%LOG%"
    echo.>> "%LOG%"
    exit /b 0
)
if !RUNNER_RESULT! EQU 3 (
    echo [%date% %time%] [PYTHON_RUNNER] Skill execution error. Falling through to Claude Code.>> "%LOG%"
)

REM RUNNER_RESULT=1: No keyword match → Claude Code needed
echo [%date% %time%] [NEW_MESSAGE] Starting Claude Code...>> "%LOG%"

REM --- Step 3: Create lock file (PID=PENDING until executor writes real PID) ---
echo pid=PENDING> "%LOCKFILE%"

REM --- Step 4: Change to project root directory ---
pushd "%ROOT%"

REM --- Step 5: Execute Claude CLI via Python wrapper (PID tracking + timeout) ---
"%VENV_PYTHON%" "%CLAUDE_EXECUTOR%" ^
  --claude-exe "%CLAUDE_EXE%" ^
  --spf "%SPF%" ^
  --lockfile "%LOCKFILE%" ^
  --log "%LOG%" ^
  --timeout %MAX_RUNTIME_SEC%

set "EC=!ERRORLEVEL!"

REM --- Step 6: Cleanup (guaranteed, even on crash) ---
if exist "%LOCKFILE%" del "%LOCKFILE%"
echo [%date% %time%] [END] Exit code: !EC!>> "%LOG%"
echo.>> "%LOG%"

popd
exit /b !EC!
