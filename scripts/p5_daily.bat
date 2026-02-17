@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8

echo ============================================================
echo   P5 일일 루틴 - %date% %time:~0,5%
echo ============================================================
echo.

cd /d "%~dp0.."
call .agent_venv\Scripts\activate.bat

echo [0/9] 텔레그램 미처리 작업 확인...
echo ────────────────────────────────────────────
python scripts\telegram\quick_check.py
if %ERRORLEVEL% EQU 0 (
    echo   새 메시지 없음. 텔레그램 단계 건너뜀.
    echo.
    goto STEP1
)
echo   새 메시지 발견. 텔레그램 작업 실행...
python scripts\telegram_task_entry.py
echo.

:STEP1
echo [1/9] Outlook 이메일 수집 + 자동 트리아지...
echo ────────────────────────────────────────────
python scripts\message_daemon.py collect outlook --limit 20 --triage
echo.

echo [2a/9] OCR 서비스 상태 점검...
echo ────────────────────────────────────────────
python scripts\p5_ocr_pipeline.py health >nul 2>&1
if errorlevel 1 (
    echo   ⚠️  OCR 서비스 불가 - OCR 단계 건너뜀
    echo.
    goto STEP3
)

echo [2b/9] 첨부파일 OCR 처리 (GLM-OCR)...
echo ────────────────────────────────────────────
python scripts\p5_ocr_pipeline.py process --limit 20
echo.

:STEP3

echo [3/10] Google Sheets → Vault 동기화...
echo ────────────────────────────────────────────
python scripts\p5_issue_sync.py sync
echo.

echo [3.5/10] Google Sheets → Notion 동기화...
echo ────────────────────────────────────────────
python scripts\p5_notion_sync.py sync
echo.

echo [3.6/10] NotebookLM Knowledge Injection (Update Context Sheet)...
echo ────────────────────────────────────────────
python scripts\p5_issue_sync.py context
echo.

echo [4/9] 메일 트리아지 (마감일/담당자 자동 추출 + OCR 데이터)...
echo ────────────────────────────────────────────
python scripts\p5_email_triage.py process --dry-run
echo.

echo [4.5/9] NotebookLM → Obsidian 동기화...
echo ────────────────────────────────────────────
python scripts\nlm_to_obsidian.py --limit 5
echo.

echo [5/9] 리뷰 큐 자동 정리 (dedup + clean)...
echo ────────────────────────────────────────────
python scripts\p5_email_triage.py queue dedup
python scripts\p5_email_triage.py queue clean --max-age 14
echo.

echo [6/9] Vault → Sheets 역동기화...
echo ────────────────────────────────────────────
python scripts\p5_issue_sync.py push
echo.

echo [7/9] 데일리 브리핑 (오늘 할 일 포함)...
echo ────────────────────────────────────────────
python scripts\p5_daily_briefing.py generate --push
echo.

echo [8/9] 운영 메트릭 대시보드...
echo ────────────────────────────────────────────
python scripts\p5_metrics.py generate
echo.

echo [9/9] 종합 상태 리포트...
echo ────────────────────────────────────────────
python scripts\p5_issue_sync.py status
echo.

echo ============================================================
echo   일일 루틴 완료!
echo ============================================================
echo.
if defined PROMPT pause
