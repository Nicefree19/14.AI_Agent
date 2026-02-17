#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Send the final result as plain text (no markdown)."""
import sys, os, io

if sys.stdout.encoding and sys.stdout.encoding.lower().startswith("cp"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
os.chdir(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from scripts.telegram.telegram_sender import send_message_sync

chat_id = 8468392331

# Part 1: 강상규 프로
msg1 = (
    "[ 윤성환 수석 / 강상규 프로 관련 최근 메일 정리 ]\n\n"
    "== 강상규 프로 (삼성E&A 구조설계그룹) ==\n\n"
    "1. 1절주 EP 계산서 회신 (2/6)\n"
    "- 1절주 삼우 배관 임베드: P/R 높이 변경 영향 고려하여 크게 반영\n"
    "  > 전환설계시 기존 임베드보다 크기가 작아지지 않도록 반영 요망\n"
    "- 2절주 UPW: 미설계 구간, 보수적으로 크게 반영\n"
    "  > H200X200 철골 거더 기준 기존 내력의 70%로 전환설계 사용 가능\n"
    "- 2절주 BCW: 명일(2/7) 송부 예정\n"
    "- 2절주 SCRUBBER: 명일(2/7) 송부 예정\n"
    ">> BCW/SCRUBBER 계산서 접수 확인 필요\n\n"
    "2. 임베드 INFORM 송부 (2/4)\n"
    "- 각 SCOPE별 임베드 INFORM 송부 완료\n"
    "- 계산서 필요 시 SCOPE별 추가 요청 가능\n\n"
    "3. 협력사 주간회의록 송부 (2/7)\n"
    "- 2026.02.03자 협력사 주간회의록\n"
    "- 노란색 부분 내용 확인 요청\n"
    "- Shop Check List 추가 사항 확인 요청\n"
    ">> 회의록 검토 및 회신 필요"
)

msg2 = (
    "== 윤성환 수석 (삼성E&A) ==\n\n"
    "윤성환 수석은 주요 메일 스레드에 CC로 포함되어 있으며,\n"
    "직접 발신한 메일은 최근 확인되지 않습니다.\n\n"
    "참여 메일 스레드:\n"
    "- 1절주 EP 변경 11~29열 (CC)\n"
    "- 2절주 EP 변경 효율화 설계 (CC)\n\n"
    "== 연관 주요 이슈 (센구조 <> 삼성E&A) ==\n\n"
    "1. EP 계산서 미접수 항목 (이동혁 소장이 강상규 프로에 요청):\n"
    "   - 2절주 BCW: B27, B45 누락\n"
    "   - 2절주 UPW: 미접수\n"
    "   - 2절주 SCRUBBER: 미접수\n"
    "   - 2절주 삼우 CCSS: 미접수\n"
    "   > 1절주 SHOP 진행 + 2절주 공기 압박으로 긴급\n\n"
    "2. 2절주 EP 변경 (효율화 설계):\n"
    "   - 변경사유: 3층 LAYOUT 변경\n"
    "   - P5: BCW/UPW/CCSS\n"
    "   - P6: UPW/SCRUBBER/CCSS\n"
    "   - EB12 상세 > 스터드 타입(왼쪽 디테일)으로 확정\n\n"
    "== 대응 필요 액션 ==\n\n"
    "1. BCW/SCRUBBER 계산서 접수 여부 확인 (2/7 송부 예정이었음)\n"
    "2. 주간회의록 검토 및 노란색 부분 회신\n"
    "3. Shop Check List 추가 사항 피드백\n"
    "4. 2절주 미접수 EP 계산서 독촉 필요 여부 판단"
)

r1 = send_message_sync(chat_id, msg1)
print(f"Part 1 sent: {r1}")

r2 = send_message_sync(chat_id, msg2)
print(f"Part 2 sent: {r2}")
