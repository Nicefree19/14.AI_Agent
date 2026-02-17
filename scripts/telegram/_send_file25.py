#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Send report file for msg_25."""
import sys, os, asyncio
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(_ROOT)
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

from dotenv import load_dotenv
load_dotenv(os.path.join(_ROOT, ".env"))

import httpx

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = 8468392331
FILE_PATH = os.path.join(_ROOT, "telegram_data", "tasks", "msg_25", "daily_report_20260213.txt")

url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
with open(FILE_PATH, "rb") as f:
    resp = httpx.post(url, data={"chat_id": CHAT_ID, "caption": "P5 이동혁 소장 일일 업무보고서 (2026-02-13)"}, files={"document": ("daily_report_20260213.txt", f)}, timeout=30)
if resp.status_code == 200 and resp.json().get("ok"):
    print("FILE_SENT")
else:
    print(f"FILE_ERROR: {resp.text}")
