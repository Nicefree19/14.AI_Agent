"""
Email Fetcher for ResearchVault
Fetches recent emails via IMAP, converts to Markdown, and saves to Obsidian.
"""

import imaplib
import email
import os
import json
import re
from email.header import decode_header
from datetime import datetime
from pathlib import Path
from bs4 import BeautifulSoup

# Config
BASE_DIR = Path(__file__).parent.parent
VAULT_DIR = BASE_DIR / "ResearchVault/00-Inbox/Emails"
CONFIG_FILE = BASE_DIR / "email_config.json"


def load_config():
    if not CONFIG_FILE.exists():
        print(f"Error: Config file not found at {CONFIG_FILE}")
        print(
            "Please create it with: {'email': '...', 'password': '...', 'imap_server': 'imap.gmail.com'}"
        )
        return None
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def clean_filename(subject):
    return re.sub(r'[\\/*?:"<>|]', "", subject)[:50].strip()


def get_body(msg):
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            cdispo = str(part.get("Content-Disposition"))
            if ctype == "text/plain" and "attachment" not in cdispo:
                return part.get_payload(decode=True).decode(errors="ignore")
            elif ctype == "text/html" and "attachment" not in cdispo:
                html = part.get_payload(decode=True).decode(errors="ignore")
                soup = BeautifulSoup(html, "html.parser")
                return soup.get_text(separator="\n")
    else:
        return msg.get_payload(decode=True).decode(errors="ignore")
    return ""


def fetch_emails(limit=5):
    config = load_config()
    if not config:
        return

    try:
        mail = imaplib.IMAP4_SSL(config["imap_server"])
        mail.login(config["email"], config["password"])
        mail.select("inbox")

        # Search for all emails (can filter by UNSEEN or SINCE)
        status, messages = mail.search(None, "UNSEEN")
        email_ids = messages[0].split()

        # Process last N emails
        for i in email_ids[-limit:]:
            res, msg_data = mail.fetch(i, "(RFC822)")
            for response_part in msg_data:
                if isinstance(response_part, tuple):
                    msg = email.message_from_bytes(response_part[1])
                    subject, encoding = decode_header(msg["Subject"])[0]
                    if isinstance(subject, bytes):
                        subject = subject.decode(encoding or "utf-8")

                    sender = msg.get("From")
                    date_str = msg.get("Date")

                    body = get_body(msg)

                    # Save to Markdown
                    safe_subject = clean_filename(subject)
                    filename = f"{datetime.now().strftime('%Y%m%d')}_{safe_subject}.md"
                    filepath = VAULT_DIR / filename

                    content = f"""---
type: email
sender: {sender}
date: {date_str}
subject: {subject}
status: inbox
---
# {subject}

**From:** {sender}
**Date:** {date_str}

---

{body}
"""
                    filepath.write_text(content, encoding="utf-8")
                    print(f"Saved: {filename}")

        mail.close()
        mail.logout()

    except Exception as e:
        print(f"Error fetching emails: {e}")


if __name__ == "__main__":
    VAULT_DIR.mkdir(parents=True, exist_ok=True)
    fetch_emails()
