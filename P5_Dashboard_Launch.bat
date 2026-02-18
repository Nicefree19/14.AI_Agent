@echo off
title P5 Command Center
echo ==========================================
echo      P5 PROJECT COMMAND CENTER
echo ==========================================
echo.

echo [1/2] Updating Intelligence Data...
python scripts/p5_dashboard_data.py
if %errorlevel% neq 0 (
    echo [ERROR] Failed to generate data.
    pause
    exit /b %errorlevel%
)

echo.
echo [2/2] Launching Interface...
cd dashboard
npm run dev
