"""
KakaoTalk Message Importer
Parses KakaoTalk text export files and converts them to ResearchVault markdown.
"""

import sys
import os
import re
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).parent.parent
VAULT_DIR = BASE_DIR / "ResearchVault/00-Inbox/Messages"


def parse_kakao_pc(file_path):
    """
    Parses KakaoTalk PC Version Export Format
    Format: [Name] [Time] Message
    """
    content = Path(file_path).read_text(encoding="utf-8")
    lines = content.splitlines()

    messages = []
    current_date = ""

    # Regex for "Date" lines (e.g., --------------- 2024년 2월 4일 일요일 ---------------)
    date_pattern = re.compile(r"-+ (\d{4}년 \d{1,2}월 \d{1,2}일 .*) -+")
    # Regex for Message lines (e.g., [Name] [AM 10:30] Message)
    msg_pattern = re.compile(r"\[(.*?)\] \[(.*?)\] (.*)")

    for line in lines:
        date_match = date_pattern.search(line)
        if date_match:
            current_date = date_match.group(1)
            continue

        msg_match = msg_pattern.match(line)
        if msg_match:
            name, time, text = msg_match.groups()
            messages.append(
                {"date": current_date, "name": name, "time": time, "text": text}
            )

    return messages


def save_as_markdown(messages, source_name):
    """Saves parsed messages as a daily digest or topic file"""
    if not messages:
        print("No messages parsed.")
        return

    # Group by Date
    grouped = {}
    for msg in messages:
        d = msg["date"] or "Unknown Date"
        if d not in grouped:
            grouped[d] = []
        grouped[d].append(msg)

    for date_str, msgs in grouped.items():
        # Convert Korean date to filename format if possible, else use raw
        # Assuming format "2024년 2월 4일 ..."
        try:
            dt = datetime.strptime(
                date_str.split(" ")[0]
                + date_str.split(" ")[1]
                + date_str.split(" ")[2],
                "%Y년%m월%d일",
            )
            file_date = dt.strftime("%Y-%m-%d")
        except:
            file_date = "Message_Log"

        clean_source = re.sub(r'[\\/:*?"<>|]', "", source_name)
        filename = f"{file_date}_{clean_source}.md"
        filepath = VAULT_DIR / filename

        md_content = f"""---
type: message-log
source_file: {source_name}
date: {file_date}
tags: [message/kakao]
---
# Chat Log: {source_name} ({date_str})

"""
        for m in msgs:
            md_content += f"- **{m['name']}** ({m['time']}): {m['text']}\n"

        filepath.write_text(md_content, encoding="utf-8")
        print(f"Saved: {filename}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python import_messages.py <kakaotalk_export.txt>")
        sys.exit(1)

    input_file = sys.argv[1]
    if not os.path.exists(input_file):
        print(f"File not found: {input_file}")
        sys.exit(1)

    VAULT_DIR.mkdir(parents=True, exist_ok=True)
    msgs = parse_kakao_pc(input_file)
    save_as_markdown(msgs, Path(input_file).stem)
