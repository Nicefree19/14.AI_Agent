#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Send PPT via Outlook email to dhlee@senkuzo.com."""
import sys, os, io, pythoncom

if sys.stdout.encoding and sys.stdout.encoding.lower().startswith("cp"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(_ROOT)

PPT_PATH = os.path.join(_ROOT, "telegram_data", "tasks", "msg_46", "P5_센코어테크_제작현황_분석.pptx")

if not os.path.exists(PPT_PATH):
    print(f"ERROR: PPT file not found: {PPT_PATH}")
    sys.exit(1)

print(f"PPT file: {PPT_PATH}")
print(f"Size: {os.path.getsize(PPT_PATH):,} bytes")

pythoncom.CoInitialize()

try:
    import win32com.client

    outlook = win32com.client.Dispatch("Outlook.Application")
    mail = outlook.CreateItem(0)  # olMailItem

    mail.To = "dhlee@senkuzo.com"
    mail.Subject = "[P5 복합동] 센코어테크 제작현황 분석 보고서 (2026.02.09 기준)"
    mail.Body = """이동혁 소장님,

P5 복합동 센코어테크 제작현황 분석 보고서를 첨부드립니다.

■ 분석 기준일: 2026-02-09
■ 원본: 원유엽 이사(센코어테크) → 류재호 전무 전달분
■ 파일: 26.2.09 P5복합동 생산(출하)일보 - 센코어테크.xlsx 분석

[주요 현황 요약]
• 총 PSRC 계획: 3,886 PCS (1~8절주)
• 1절주 제작완료: 177/737 (24.0%)
• 앙카 생산: 421/737 (57.1%), 출하: 249/737 (33.8%)

[주의 사항]
• C존(센코어 설치구간) 1절주: 미착수 (0/176)
• 대성1/동명/오창: 1절 PSRC 미착수
• PTW 철근 과다로 제작 지연
• FMCS 오류로 실적 등록 불가

상세 내용은 첨부 PPT를 참조 부탁드립니다.

※ 본 메일은 자비스(AI 비서)가 자동 분석하여 발송한 보고서입니다.
"""

    mail.Attachments.Add(PPT_PATH)
    mail.Send()
    print("Email sent successfully to dhlee@senkuzo.com")

except Exception as e:
    print(f"ERROR sending email: {e}")
    sys.exit(1)

finally:
    pythoncom.CoUninitialize()
