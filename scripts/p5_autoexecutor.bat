@echo off
setlocal EnableExtensions

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

REM --- Process Guard: Skip if Claude already running ---
tasklist /FI "IMAGENAME eq claude.exe" /FO CSV 2>NUL | findstr /I "claude" >NUL
if %ERRORLEVEL% EQU 0 (
    echo [%date% %time%] [SKIP] Claude process already running>> "%LOG%"
    exit /b 98
)

REM --- Stale Lock Recovery: No process + lock exists = stale ---
if exist "%LOCKFILE%" (
    echo [%date% %time%] [WARN] Stale lock removed (no Claude process)>> "%LOG%"
    del "%LOCKFILE%"
)

echo [%date% %time%] [START] Claude CLI: %CLAUDE_EXE%>> "%LOG%"

REM --- Step 1: Quick check (message + lock state) ---
"%VENV_PYTHON%" "%QUICK_CHECK%" 2>>"%LOG%"
set CHECK_RESULT=%ERRORLEVEL%

if %CHECK_RESULT% EQU 0 (
    echo [%date% %time%] [NO_MESSAGE] No new messages.>> "%LOG%"
    exit /b 0
)
if %CHECK_RESULT% EQU 2 (
    echo [%date% %time%] [LOCKED] Another task in progress.>> "%LOG%"
    exit /b 98
)
if %CHECK_RESULT% EQU 3 (
    echo [%date% %time%] [ERROR] Check failed. Will retry.>> "%LOG%"
    exit /b 0
)

REM CHECK_RESULT=1: New messages found
echo [%date% %time%] [NEW_MESSAGE] Starting Claude Code...>> "%LOG%"

REM --- Step 2: Create lock file (atomic: fails silently if exists) ---
copy NUL "%LOCKFILE%" >NUL 2>&1

REM --- Step 3: Change to project root directory ---
pushd "%ROOT%"

REM --- Step 4: Execute Claude CLI (try resume first, then new session) ---
call "%CLAUDE_EXE%" -p -c --dangerously-skip-permissions ^
  --append-system-prompt-file "%SPF%" ^
  "Telegram message check and process. All APIs are in scripts/telegram/telegram_bot.py, sending uses scripts/telegram/telegram_sender.py send_message_sync(). If new messages: 1) check_telegram() to check, 2) combine_tasks() to merge, 3) send_message_sync() for immediate reply, 4) create_working_lock(), 5) reserve_memory_telegram(), 6) load_memory() to review past work, 7) execute task (report progress via send_message_sync()), 8) report_telegram(), 9) mark_done_telegram(), 10) remove_working_lock(). After task completion, ask user if there are more tasks, then wait 3 minutes checking for new telegram messages; if found continue processing (repeat this loop until user stops or no response), then exit completely. When reporting progress via telegram, include key details and issues concisely." ^
  >> "%LOG%" 2>&1

set "EC=%ERRORLEVEL%"

REM If resume failed, try new session
if %EC% NEQ 0 (
    echo [%date% %time%] [INFO] Resume failed (EC=%EC%). Starting new session...>> "%LOG%"
    call "%CLAUDE_EXE%" -p --dangerously-skip-permissions ^
      --append-system-prompt-file "%SPF%" ^
      "Telegram message check and process. All APIs are in scripts/telegram/telegram_bot.py, sending uses scripts/telegram/telegram_sender.py send_message_sync(). If new messages: 1) check_telegram() to check, 2) combine_tasks() to merge, 3) send_message_sync() for immediate reply, 4) create_working_lock(), 5) reserve_memory_telegram(), 6) load_memory() to review past work, 7) execute task (report progress via send_message_sync()), 8) report_telegram(), 9) mark_done_telegram(), 10) remove_working_lock(). After task completion, ask user if there are more tasks, then wait 3 minutes checking for new telegram messages; if found continue processing (repeat this loop until user stops or no response), then exit completely. When reporting progress via telegram, include key details and issues concisely." ^
      >> "%LOG%" 2>&1
    set "EC=%ERRORLEVEL%"
)

REM --- Step 5: Cleanup (guaranteed, even on crash) ---
if exist "%LOCKFILE%" del "%LOCKFILE%"
echo [%date% %time%] [END] Exit code: %EC%>> "%LOG%"
echo.>> "%LOG%"

popd
exit /b %EC%
