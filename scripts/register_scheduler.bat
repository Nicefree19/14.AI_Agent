@echo off
chcp 65001 >NUL
setlocal EnableExtensions

echo ========================================
echo Windows Task Scheduler Registration
echo P5 Agent - Claude Code Auto Executor
echo ========================================
echo.

REM Auto-detect project paths
set "SCRIPT_DIR=%~dp0"
set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
set "PROJECT_DIR=%SCRIPT_DIR%\.."
for %%I in ("%PROJECT_DIR%") do set "PROJECT_DIR=%%~fI"
set "BAT_FILE=%SCRIPT_DIR%\p5_autoexecutor.bat"

REM Extract folder name for multi-bot support
for %%I in ("%PROJECT_DIR%") do set "FOLDER_NAME=%%~nxI"

REM Dynamic task name based on folder
set "TASK_NAME=Claude_P5Agent_%FOLDER_NAME%"

echo Project Path:  %PROJECT_DIR%
echo Folder Name:   %FOLDER_NAME%
echo Task Name:     %TASK_NAME%
echo Executor:      %BAT_FILE%
echo Mode:          Foreground (GUI capable)
echo.

REM Check admin privileges
net session >NUL 2>&1
if errorlevel 1 (
    echo [ERROR] Administrator privileges required!
    echo         Right-click this file and select "Run as administrator"
    pause
    exit /b 1
)

REM Get current user account
for /f "tokens=*" %%u in ('whoami') do set "CURRENT_USER=%%u"
echo Run as user:   %CURRENT_USER%
echo.

echo [TASK] Removing existing task (if any)...
schtasks /Delete /TN "%TASK_NAME%" /F >NUL 2>&1

echo [TASK] Registering new task (every 1 minute, foreground mode)...
schtasks /Create /TN "%TASK_NAME%" /TR "\"%BAT_FILE%\"" /SC MINUTE /MO 1 /RL HIGHEST /IT /RU "%CURRENT_USER%" /F
if errorlevel 1 (
    echo [ERROR] Task registration failed!
    pause
    exit /b 1
)

echo.
echo ========================================
echo Task Scheduler Registration Complete!
echo ========================================
echo.
echo Task Name:   %TASK_NAME%
echo Interval:    Every 1 minute
echo Executor:    %BAT_FILE%
echo Mode:        Foreground (GUI capable)
echo Run as:      %CURRENT_USER%
echo.
echo Notes:
echo   - Foreground mode only works when user is logged in
echo   - Chrome, Playwright and other GUI programs can run
echo.
echo Management commands:
echo   Disable: schtasks /Change /TN "%TASK_NAME%" /DISABLE
echo   Enable:  schtasks /Change /TN "%TASK_NAME%" /ENABLE
echo   Delete:  schtasks /Delete /TN "%TASK_NAME%" /F
echo   Query:   schtasks /Query /TN "%TASK_NAME%" /FO LIST
echo.
pause
