"""
P5 Voice Scribe (Gemini 1.5 Pro Powered)
----------------------------------------
Two-Track System for processing STT transcripts from Naver Clova Note / T-Lo.

Modes:
1. Call Mode (Call_*.txt): Focus on immediate actions & clarifications.
2. Meeting Mode (Meeting_*.txt): Focus on decisions, issue mapping & assignments.

Usage:
    Running this script starts a Watchdog for `ResearchVault/Inbox/Clova`.
    Simply drop a .txt file there to process.
"""

import os
import sys
import time
import json
import yaml
import re
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# ─── Configuration ──────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
VAULT_PATH = PROJECT_ROOT / "ResearchVault"
INBOX_DIR = VAULT_PATH / "Inbox" / "Clova"
ISSUES_DIR = VAULT_PATH / "P5-Project" / "01-Issues"
MEETING_DIR = VAULT_PATH / "P5-Project" / "03-Meetings"
TERMS_FILE = SCRIPT_DIR / "p5_terms.yaml"

# Logging Setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - [VoiceScribe] %(message)s",
    handlers=[
        logging.FileHandler(SCRIPT_DIR / "p5_voice_scribe.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("VoiceScribe")

# Ensure Directories
INBOX_DIR.mkdir(parents=True, exist_ok=True)
MEETING_DIR.mkdir(parents=True, exist_ok=True)


# ─── Gemini API Wrapper (Placeholder) ───────────────────────
# 실제 API 연동을 위해서는 google-generativeai 패키지가 필요합니다.
# 현재 환경에서는 Mock 또는 실제 구현을 선택해야 합니다.
# 여기서는 실제 구현을 위한 구조를 잡습니다.

try:
    import google.generativeai as genai

    # API KEY는 환경변수 또는 .env에서 로드
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")

    api_key = os.getenv("GEMINI_API_KEY")
    if api_key:
        genai.configure(api_key=api_key)
    else:
        log.warning("GEMINI_API_KEY not found. Operations will fail.")
except ImportError:
    log.warning("google-generativeai package not installed.")


class ExternalModel:
    """Gemini 1.5 Pro Interface"""

    def __init__(self, model_name="gemini-1.5-pro-latest"):
        self.model = genai.GenerativeModel(model_name)

    def generate(self, prompt: str) -> str:
        try:
            response = self.model.generate_content(prompt)
            return response.text
        except Exception as e:
            log.error(f"Gemini API Error: {e}")
            return ""


# ─── Context Builders ───────────────────────────────────────


def load_terms() -> str:
    """p5_terms.yaml 로드하여 문자열 변환"""
    if not TERMS_FILE.exists():
        return "No dictionary found."

    try:
        data = yaml.safe_load(TERMS_FILE.read_text(encoding="utf-8"))
        return yaml.dump(data, allow_unicode=True)
    except Exception as e:
        log.error(f"Failed to load terms: {e}")
        return ""


def load_active_issues() -> str:
    """최근 Critical/High 이슈 리스트 로드"""
    issues = []
    if ISSUES_DIR.exists():
        for f in ISSUES_DIR.glob("SEN-*.md"):
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
                if "priority: critical" in content or "priority: high" in content:
                    # YAML parsing simplified
                    lines = content.splitlines()
                    title = "Untitled"
                    issue_id = f.stem
                    for line in lines[:20]:
                        if line.startswith("title:"):
                            title = line.replace("title:", "").strip().strip('"')
                        if line.startswith("issue_id:"):
                            issue_id = line.replace("issue_id:", "").strip().strip('"')

                    issues.append(f"- [{issue_id}] {title}")
            except Exception:
                continue

    return "\n".join(issues[:30])  # Top 30 only to save tokens


# ─── Prompt Templates ───────────────────────────────────────

BRIDGE_PROMPT_TEMPLATE = """
너는 P5 프로젝트 {MODE} 기록 정제 및 구조화 전문가다.
중요: 사실 기반으로만 작성하고 추측은 금지한다.
내가 준 STT 원문만 사용한다.

[목표]
- STT 오인식 교정 (용어 사전 참고)
- 프로젝트 용어 정규화
- 이슈/결정/액션 추출
- 텔레그램 전달용 중간 메시지 생성

[규칙]
1) 의미 변경 금지, STT 오류만 교정
2) 불확실 항목은 반드시 NEED_CONFIRMATION으로 분리
3) issue_id는 원문에 있을 때만 사용 (없으면 NEW_CANDIDATE)
4) priority는 critical/high/medium/low로 정규화
5) 날짜는 YYYY-MM-DD 형식
6) 출력은 아래 8개 섹션만 제공

[프로젝트 용어 사전]
{TERMS}

[현재 활성 이슈 리스트 (참고용)]
{ACTIVE_ISSUES}

[출력 형식]
SECTION 1: CORRECTED_TEXT
...
SECTION 2: SUMMARY_5_LINES
...
SECTION 3: DECISIONS
...
SECTION 4: ACTION_ITEMS
...
SECTION 5: ISSUE_UPDATES
...
SECTION 6: NEED_CONFIRMATION
...
SECTION 7: TELEGRAM_SEND_TEXT
...
SECTION 8: BRIDGE_V1
[MEETING_BRIDGE_V1]
...
[/MEETING_BRIDGE_V1]

[입력 STT]
<<<
{INPUT_TEXT}
>>>
"""

# ─── Processing Logic ───────────────────────────────────────


def process_file(file_path: Path):
    log.info(f"Processing file: {file_path.name}")

    # 1. Determine Mode
    filename = file_path.name.lower()
    if "call" in filename or "통화" in filename:
        mode = "통화(Call)"
    else:
        mode = "회의(Meeting)"

    log.info(f"Detected Mode: {mode}")

    # 2. Read Content
    try:
        text = file_path.read_text(encoding="utf-8")
    except Exception:
        # CP949 Fallback for Windows
        try:
            text = file_path.read_text(encoding="cp949")
        except Exception as e:
            log.error(f"Failed to read file: {e}")
            return

    # 3. Build Prompt
    terms = load_terms()
    active_issues = load_active_issues()
    prompt = BRIDGE_PROMPT_TEMPLATE.format(
        MODE=mode, TERMS=terms, ACTIVE_ISSUES=active_issues, INPUT_TEXT=text
    )

    # 4. Process with Gemini
    gemini = ExternalModel("gemini-1.5-pro-latest")
    result = gemini.generate(prompt)

    if not result:
        log.error("Empty response from Gemini.")
        return

    # 5. Save Output
    output_filename = (
        f"{datetime.now().strftime('%Y%m%d')}-{file_path.stem}-Analysis.md"
    )
    output_path = MEETING_DIR / output_filename

    final_output = f"""---
title: "{mode} 요약: {file_path.stem}"
date: {datetime.now().strftime('%Y-%m-%d')}
tags: [type/{'call' if 'Call' in mode else 'meeting'}]
original_file: {file_path.name}
---

# 📝 {mode} 분석 결과

{result}
"""
    output_path.write_text(final_output, encoding="utf-8")
    log.info(f"Analysis saved to: {output_path}")

    # 6. Telegram Notification (Extract Section 7)
    try:
        if "SECTION 7: TELEGRAM_SEND_TEXT" in result:
            parts = result.split("SECTION 7: TELEGRAM_SEND_TEXT")[1]
            # Next section split
            if "SECTION 8" in parts:
                msg_body = parts.split("SECTION 8")[0].strip()
            else:
                msg_body = parts.strip()

            send_telegram_alert(f"🎙️ **{mode} 분석 완료**\n\n{msg_body}")
    except Exception as e:
        log.error(f"Failed to send Telegram: {e}")

    # 7. Move processed file to Archive (Optional)
    # processed_dir = INBOX_DIR / "Processed"
    # processed_dir.mkdir(exist_ok=True)
    # file_path.rename(processed_dir / file_path.name)


def send_telegram_alert(message: str):
    """Call external telegram script or API"""
    # Assuming scripts/telegram/telegram_sender.py exists or similar
    # For now, we'll implement a simple subprocess call if needed,
    # but strictly speaking we should reuse existing tools.
    # Here we will just log it as the user didn't ask for full implementation yet.
    log.info(f"[TELEGRAM] {message}")

    # Try using the existing telegram_sender if available
    try:
        sys.path.append(str(SCRIPT_DIR / "telegram"))
        from telegram_sender import send_message

        send_message(message)
    except ImportError:
        pass


# ─── Watchdog Handler ───────────────────────────────────────


class VoiceInboxHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory:
            return

        filename = Path(event.src_path).name
        if filename.endswith(".txt") or filename.endswith(".md"):
            # Wait for file write to complete
            time.sleep(1)
            process_file(Path(event.src_path))


def start_watchdog():
    observer = Observer()
    event_handler = VoiceInboxHandler()
    observer.schedule(event_handler, str(INBOX_DIR), recursive=False)
    observer.start()
    log.info(f"👀 Watching {INBOX_DIR} for Voice Transcripts...")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == "__main__":
    # If file argument provided, process immediately
    if len(sys.argv) > 1:
        fpath = Path(sys.argv[1])
        if fpath.exists():
            process_file(fpath)
        else:
            print(f"File not found: {fpath}")
    else:
        # Otherwise start watchdog
        start_watchdog()
