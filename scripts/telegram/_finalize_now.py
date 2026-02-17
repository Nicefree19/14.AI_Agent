#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Step 8-10: Report result, mark done, remove lock - msg_52."""
import sys, os, io

if sys.stdout.encoding and sys.stdout.encoding.lower().startswith("cp"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
os.chdir(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from scripts.telegram.telegram_bot import (
    report_telegram,
    mark_done_telegram,
    remove_working_lock,
)

# ---- Inline task data ----
chat_id = 8468392331
message_ids = [52]
timestamps = ["2026-02-13 23:53:43"]
instruction = "내 폴더내에 P5 프로젝트 폴더내 P5 현황 대시보드를 만든 폴더가 있어 해당 내용 분석해서 위 제작현환분석을 업데이트해줘"

result_text = """센코어테크 제작현황 + P5 대시보드 통합 PPT 업데이트 완료!

📊 PPT 구성 (9슬라이드 - 기존 6p + 신규 3p):

[기존] 센코어테크 생산일보 분석
1. 표지 - P5 복합동 PSRC 제작현황 분석 (통합)
2. Executive Summary - KPI 대시보드 (긴급 이슈 5건 추가)
3. 1절주/2절주 제작현황 (갑지)
4. 업체별 공정현황 집계표 (앙카 + PSRC)
5. 일일 생산집계 & 원자재 현황
6. 제작이슈 정리 & 류재호 전무님 코멘트

[신규] P5 대시보드 데이터 통합
7. 즉시 조치 항목 & Critical/High SEN 이슈 (5건)
8. SHOP REV 일정표 (양재영 이사 2/6 확정판) + 미결 의사결정
9. 데이터 품질 경고 & 다음 주 업무 계획 (2/11~2/14)

📧 이메일 발송 완료:
- 수신: dhlee@senkuzo.com (이동혁 소장님)
- 제목: [P5 복합동] 센코어테크 제작현황 통합분석 보고서 - 업데이트

📌 주요 대시보드 데이터:
- 긴급: PSRC Rev.3 검토 회신 (2/11), EP-105~108 검토 (SEN-668)
- 앙카 HOLD 해제 조건 미확정 (SEN-097)
- 담당자 미지정 669/671건 (100%)"""

# PPT file
ppt_file = os.path.join(
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")),
    "telegram_data", "tasks", "msg_52", "P5_센코어테크_제작현황_통합분석.pptx"
)
files = [ppt_file] if os.path.exists(ppt_file) else []

# Step 8: Report
print("Sending report...")
report_telegram(
    instruction=instruction,
    result_text=result_text,
    chat_id=chat_id,
    timestamp=timestamps,
    message_id=message_ids,
    files=files,
)
print("Report sent")

# Step 8b: Send file separately via httpx (backup for broken file attachment)
if files:
    try:
        import httpx
        from dotenv import load_dotenv
        load_dotenv()
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        for fpath in files:
            fname = os.path.basename(fpath)
            url = f"https://api.telegram.org/bot{token}/sendDocument"
            with open(fpath, "rb") as f:
                resp = httpx.post(url, data={"chat_id": chat_id}, files={"document": (fname, f)}, timeout=30)
            print(f"File sent via httpx: {fname} -> {resp.status_code}")
    except Exception as e:
        print(f"File send backup failed: {e}")

# Step 9: Mark done
print("Marking done...")
mark_done_telegram(message_ids)
print("Marked done")

# Step 10: Remove lock
print("Removing lock...")
remove_working_lock()
print("Lock removed")
print("DONE")
