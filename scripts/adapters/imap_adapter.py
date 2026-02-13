"""
IMAP Adapter for Email Collection
Fetches emails via IMAP (Gmail, etc.) and converts to unified message format.
"""

import imaplib
import email
import email.message
import json
import logging
from email.header import decode_header
from datetime import datetime
from pathlib import Path
from typing import List, Optional, TYPE_CHECKING

from bs4 import BeautifulSoup

from .base import MessageAdapter, UnifiedMessage

if TYPE_CHECKING:
    from email.message import Message as EmailMessage

log = logging.getLogger(__name__)


class IMAPAdapter(MessageAdapter):
    """IMAP email adapter for Gmail and other IMAP servers."""

    adapter_name = "imap"
    source_type = "email"
    supports_watch = False
    poll_interval = 10  # minutes

    def __init__(self, config: Optional[dict] = None):
        super().__init__(config)
        self.mail: Optional[imaplib.IMAP4_SSL] = None
        self._config_file = self.config.get(
            "config_file",
            Path(__file__).parent.parent.parent / "email_config.json"
        )

    def _load_credentials(self) -> Optional[dict]:
        """Load email credentials from config file."""
        config_path = Path(self._config_file)
        if not config_path.exists():
            log.error(f"Config file not found: {config_path}")
            log.info("Create email_config.json with: {'email': '...', 'password': '...', 'imap_server': 'imap.gmail.com'}")
            return None

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log.error(f"Failed to load config: {e}")
            return None

    def initialize(self) -> bool:
        """Connect to IMAP server."""
        creds = self._load_credentials()
        if not creds:
            return False

        try:
            self.mail = imaplib.IMAP4_SSL(creds.get("imap_server", "imap.gmail.com"))
            self.mail.login(creds["email"], creds["password"])
            self._initialized = True
            log.info(f"Connected to IMAP server: {creds.get('imap_server')}")
            return True
        except Exception as e:
            log.error(f"IMAP connection failed: {e}")
            return False

    def _decode_header_value(self, value: str) -> str:
        """Decode email header value."""
        if not value:
            return ""
        decoded_parts = []
        for part, encoding in decode_header(value):
            if isinstance(part, bytes):
                decoded_parts.append(part.decode(encoding or "utf-8", errors="ignore"))
            else:
                decoded_parts.append(part)
        return " ".join(decoded_parts)

    def _get_body(self, msg) -> str:
        """Extract body from email message."""
        if msg.is_multipart():
            for part in msg.walk():
                ctype = part.get_content_type()
                cdispo = str(part.get("Content-Disposition", ""))

                if ctype == "text/plain" and "attachment" not in cdispo:
                    payload = part.get_payload(decode=True)
                    if payload:
                        return payload.decode(errors="ignore")

                elif ctype == "text/html" and "attachment" not in cdispo:
                    payload = part.get_payload(decode=True)
                    if payload:
                        html = payload.decode(errors="ignore")
                        soup = BeautifulSoup(html, "html.parser")
                        return soup.get_text(separator="\n")
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                return payload.decode(errors="ignore")

        return ""

    def _parse_date(self, date_str: Optional[str]) -> datetime:
        """Parse email date string to datetime."""
        if not date_str:
            return datetime.now()

        try:
            from email.utils import parsedate_to_datetime
            return parsedate_to_datetime(date_str)
        except Exception:
            return datetime.now()

    def fetch(
        self,
        limit: int = 10,
        folder: str = "inbox",
        criteria: str = "UNSEEN",
        **kwargs
    ) -> List[UnifiedMessage]:
        """
        Fetch emails from IMAP server.

        Args:
            limit: Maximum number of emails to fetch
            folder: Mailbox folder to fetch from
            criteria: IMAP search criteria (ALL, UNSEEN, SINCE, etc.)

        Returns:
            List of UnifiedMessage objects
        """
        if not self._initialized:
            if not self.initialize():
                return []

        messages = []

        try:
            self.mail.select(folder)
            status, data = self.mail.search(None, criteria)

            if status != "OK":
                log.warning(f"Search failed: {status}")
                return []

            email_ids = data[0].split()
            # Get most recent emails
            email_ids = email_ids[-limit:]

            for email_id in email_ids:
                try:
                    res, msg_data = self.mail.fetch(email_id, "(RFC822)")

                    for response_part in msg_data:
                        if isinstance(response_part, tuple):
                            msg = email.message_from_bytes(response_part[1])

                            subject = self._decode_header_value(msg.get("Subject", ""))
                            sender = self._decode_header_value(msg.get("From", ""))
                            date_str = msg.get("Date")
                            message_id = msg.get("Message-ID", str(email_id.decode()))

                            body = self._get_body(msg)
                            timestamp = self._parse_date(date_str)

                            unified_msg = UnifiedMessage(
                                id=message_id,
                                source_type="email",
                                source_adapter="imap",
                                sender=sender,
                                subject=subject,
                                body=body,
                                timestamp=timestamp,
                                raw_metadata={
                                    "folder": folder,
                                    "criteria": criteria,
                                    "email_id": email_id.decode(),
                                }
                            )
                            messages.append(unified_msg)

                except Exception as e:
                    log.warning(f"Failed to process email {email_id}: {e}")
                    continue

            log.info(f"Fetched {len(messages)} emails from {folder}")

        except Exception as e:
            log.error(f"Error fetching emails: {e}")

        return messages

    def fetch_all(self, limit: int = 10, folder: str = "inbox") -> List[UnifiedMessage]:
        """Fetch all emails (not just unread)."""
        return self.fetch(limit=limit, folder=folder, criteria="ALL")

    def close(self):
        """Close IMAP connection."""
        if self.mail:
            try:
                self.mail.close()
                self.mail.logout()
            except Exception:
                pass
            self.mail = None
            self._initialized = False
            log.info("IMAP connection closed")


# Compatibility wrapper for existing fetch_emails.py usage
def fetch_emails(limit: int = 5, output_dir: Optional[Path] = None):
    """
    Legacy-compatible function for fetching emails.

    Args:
        limit: Number of emails to fetch
        output_dir: Directory to save markdown files
    """
    if output_dir is None:
        output_dir = Path(__file__).parent.parent.parent / "ResearchVault/00-Inbox/Emails"

    output_dir.mkdir(parents=True, exist_ok=True)

    with IMAPAdapter() as adapter:
        messages = adapter.fetch(limit=limit)
        for msg in messages:
            filepath = adapter.save_message(msg, output_dir)
            print(f"Saved: {filepath.name}")

    return len(messages)


if __name__ == "__main__":
    # Quick test
    logging.basicConfig(level=logging.INFO)
    fetch_emails(limit=3)
