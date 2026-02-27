#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Send updated PPT via Outlook COM to dhlee@senkuzo.com."""
import sys, os, io, pythoncom

if sys.stdout.encoding and sys.stdout.encoding.lower().startswith("cp"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PPT_PATH = os.path.join(_ROOT, "telegram_data", "tasks", "msg_52", "P5_센코어테크_제작현황_통합분석.pptx")

if not os.path.exists(PPT_PATH):
    print(f"ERROR: PPT not found: {PPT_PATH}")
    sys.exit(1)

pythoncom.CoInitialize()

try:
    import win32com.client
    outlook = win32com.client.Dispatch("Outlook.Application")
    mail = outlook.CreateItem(0)  # olMailItem

    mail.To = "dhlee@senkuzo.com"
    mail.Subject = "[P5 복합동] 센코어테크 제작현황 통합분석 보고서 (2026.02.09~02.11 기준) - 업데이트"
    mail.Body = """이동혁 소장님께,

P5 복합동 센코어테크 제작현황 분석 보고서를 업데이트하여 보내드립니다.

[업데이트 내용]
기존 제작현황 분석(6슬라이드)에 P5 대시보드 데이터를 추가하여 총 9슬라이드로 확장했습니다.

▶ 기존 (Slide 1~6): 센코어테크 생산일보 기반 제작현황
  - 총괄 KPI, 1절주/2절주 현황, 업체별 집계표, 일일생산, 원자재, 이슈정리

▶ 추가 (Slide 7~9): P5 대시보드 데이터 통합
  - Slide 7: 즉시 조치 항목 5건 & Critical/High SEN 이슈
  - Slide 8: SHOP REV 일정표 (양재영 이사 2/6 확정판) & 미결 의사결정
  - Slide 9: 데이터 품질 경고 & 다음 주 업무 계획 (2/11~2/14)

[핵심 포인트]
- 전체 PSRC 진행률: 4.6% (177/3,886 PCS)
- 1절 PSRC: 24.0% | 앙카: 57.1%
- 긴급: PSRC Rev.3 검토 회신 (2/11 마감), EP-105~108 검토
- 주의: 담당자 미지정 669/671건, 앙카 HOLD 미해제

감사합니다.

---
자비스(AI 비서)
센구조연구소 EPC팀
"""

    mail.Attachments.Add(PPT_PATH)
    mail.Send()
    print(f"Email sent to: dhlee@senkuzo.com")
    print(f"Subject: {mail.Subject}")
    print(f"Attachment: {os.path.basename(PPT_PATH)} ({os.path.getsize(PPT_PATH):,} bytes)")
    print("SUCCESS")

finally:
    pythoncom.CoUninitialize()
