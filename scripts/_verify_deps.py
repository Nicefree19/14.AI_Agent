#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
의존성 검증 스크립트 — P5 Agent 전체 런타임 의존성 확인

Exit Codes:
  0: 모든 의존성 정상
  1: 필수 의존성 누락
"""
import sys

missing = []

print(f"Python: {sys.version}")

# ── OCR / 문서 처리 ──
try:
    import fitz
    print(f"  PyMuPDF: {fitz.version[0]}")
except ImportError as e:
    print(f"  PyMuPDF: MISSING - {e}")
    missing.append("PyMuPDF")

try:
    from PIL import Image
    print("  Pillow: OK")
except ImportError as e:
    print(f"  Pillow: MISSING - {e}")
    missing.append("Pillow")

# ── 네트워크 / 설정 ──
try:
    import requests
    print("  requests: OK")
except ImportError as e:
    print(f"  requests: MISSING - {e}")
    missing.append("requests")

try:
    import yaml
    print("  yaml: OK")
except ImportError as e:
    print(f"  yaml: MISSING - {e}")
    missing.append("PyYAML")

# ── Telegram 봇 ──
try:
    # scripts/telegram/ 패키지와 이름 충돌 우회
    import importlib
    _orig = sys.modules.pop("telegram", None)
    _subs = {k: v for k, v in sys.modules.items() if k.startswith("telegram.")}
    for k in _subs:
        sys.modules.pop(k, None)
    try:
        tg = importlib.import_module("telegram")
        print(f"  python-telegram-bot: {tg.__version__}")
    finally:
        if _orig is not None:
            sys.modules["telegram"] = _orig
        for k, v in _subs.items():
            sys.modules[k] = v
except Exception as e:
    print(f"  python-telegram-bot: MISSING - {e}")
    missing.append("python-telegram-bot")

try:
    import dotenv
    print("  python-dotenv: OK")
except ImportError as e:
    print(f"  python-dotenv: MISSING - {e}")
    missing.append("python-dotenv")

try:
    import apscheduler
    print("  apscheduler: OK")
except ImportError as e:
    print(f"  apscheduler: MISSING - {e}")
    missing.append("APScheduler")

try:
    import watchdog
    print("  watchdog: OK")
except ImportError as e:
    print(f"  watchdog: MISSING - {e}")
    missing.append("watchdog")

# ── 결과 ──
print()
if missing:
    print(f"FAILED: {len(missing)} missing dependencies: {', '.join(missing)}")
    print(f"  Fix: pip install {' '.join(missing)}")
    sys.exit(1)
else:
    print("All dependencies verified!")
    sys.exit(0)
