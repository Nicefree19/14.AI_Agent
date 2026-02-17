@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8

echo ============================================================
echo   P5 주간 루틴 - %date%
echo ============================================================
echo.

cd /d "%~dp0.."
call .agent_venv\Scripts\activate.bat

echo [1/10] Outlook 이메일 전체 수집 + 트리아지...
echo ────────────────────────────────────────────
python scripts\message_daemon.py collect outlook --limit 50 --triage
echo.

echo [2/10] 첨부파일 OCR 처리 (GLM-OCR)...
echo ────────────────────────────────────────────
python scripts\p5_ocr_pipeline.py process
echo.

echo [3/10] OCR 도면번호 → 이슈 연계...
echo ────────────────────────────────────────────
python scripts\p5_ocr_pipeline.py link
echo.

echo [4/10] Google Sheets → Vault 동기화...
echo ────────────────────────────────────────────
python scripts\p5_issue_sync.py sync
echo.

echo [5/10] 메일 트리아지 (마감일/담당자 자동 추출 + OCR 데이터)...
echo ────────────────────────────────────────────
python scripts\p5_email_triage.py process
echo.

echo [6/10] 리뷰 큐 자동 정리 (dedup + clean)...
echo ────────────────────────────────────────────
python scripts\p5_email_triage.py queue dedup
python scripts\p5_email_triage.py queue clean --max-age 14
echo.

echo [7/10] Vault → Sheets 역동기화...
echo ────────────────────────────────────────────
python scripts\p5_issue_sync.py push
echo.

echo [8/10] 운영 메트릭 대시보드 생성...
echo ────────────────────────────────────────────
python scripts\p5_metrics.py generate
echo.

echo [9/10] 주간 예외 보고서 생성...
echo ────────────────────────────────────────────
python scripts\p5_email_triage.py report
echo.

echo [10/11] 종합 상태 리포트...
echo ────────────────────────────────────────────
python scripts\p5_issue_sync.py status
echo.

echo [11/11] Vault 정기 백업 (01-Issues)...
echo ────────────────────────────────────────────
python scripts\p5_vault_backup.py --keep 5
echo.

echo ============================================================
echo   주간 루틴 완료!
echo   보고서: ResearchVault\P5-Project\00-Overview\주간예외보고서.md
echo   메트릭: ResearchVault\P5-Project\00-Overview\운영메트릭.md
echo ============================================================
echo.
if defined PROMPT pause
