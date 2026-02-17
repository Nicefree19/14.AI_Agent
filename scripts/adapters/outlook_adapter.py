"""
Outlook COM Adapter for Local Email Collection
Uses pywin32 COM interface to access local Outlook installation.
"""

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from .base import MessageAdapter, UnifiedMessage

log = logging.getLogger(__name__)

# Outlook folder constants (OlDefaultFolders enum)
OL_FOLDER_INBOX = 6
OL_FOLDER_SENT = 5
OL_FOLDER_DRAFTS = 16
OL_FOLDER_DELETED = 3
OL_FOLDER_OUTBOX = 4


class OutlookAdapter(MessageAdapter):
    """Outlook COM adapter for local email access on Windows."""

    adapter_name = "outlook"
    source_type = "email"
    supports_watch = True  # COM supports event notifications
    poll_interval = 5  # minutes (can poll more frequently since local)

    def __init__(self, config: Optional[dict] = None):
        super().__init__(config)
        self.outlook = None
        self.namespace = None
        self._folders = {}
        self._com_initialized = False

    def initialize(self) -> bool:
        """Initialize Outlook COM connection.

        Handles COM threading: calls CoInitialize() for background/scheduler
        threads that may not have COM initialized.
        """
        try:
            import pythoncom
            try:
                pythoncom.CoInitialize()
                self._com_initialized = True
            except Exception:
                # Already initialized on this thread (main thread case)
                self._com_initialized = False

            import win32com.client

            self.outlook = win32com.client.Dispatch("Outlook.Application")
            self.namespace = self.outlook.GetNamespace("MAPI")

            # Pre-cache default folders
            self._folders = {
                "inbox": self.namespace.GetDefaultFolder(OL_FOLDER_INBOX),
                "sent": self.namespace.GetDefaultFolder(OL_FOLDER_SENT),
                "drafts": self.namespace.GetDefaultFolder(OL_FOLDER_DRAFTS),
                "deleted": self.namespace.GetDefaultFolder(OL_FOLDER_DELETED),
                "outbox": self.namespace.GetDefaultFolder(OL_FOLDER_OUTBOX),
            }

            self._initialized = True
            log.info("Outlook COM adapter initialized")
            return True

        except ImportError:
            log.error("pywin32 not installed. Run: pip install pywin32")
            return False
        except Exception as e:
            log.error(f"Failed to initialize Outlook: {e}")
            return False

    def _convert_datetime(self, pytime) -> datetime:
        """Convert Outlook pywintypes datetime to Python datetime."""
        try:
            # pywintypes.datetime can be converted directly in most cases
            if hasattr(pytime, 'year'):
                return datetime(
                    pytime.year, pytime.month, pytime.day,
                    pytime.hour, pytime.minute, pytime.second
                )
            return datetime.now()
        except Exception:
            return datetime.now()

    def _get_folder(self, folder_name: str):
        """Get Outlook folder by name."""
        folder_name = folder_name.lower()
        if folder_name in self._folders:
            return self._folders[folder_name]

        # Try to find custom folder
        try:
            root = self.namespace.Folders
            for store in root:
                try:
                    folder = store.Folders[folder_name]
                    return folder
                except Exception:
                    continue
        except Exception:
            pass

        # Default to inbox
        return self._folders.get("inbox")

    def fetch(
        self,
        limit: int = 10,
        folder: str = "inbox",
        unread_only: bool = False,
        **kwargs
    ) -> List[UnifiedMessage]:
        """
        Fetch emails from local Outlook.

        Args:
            limit: Maximum number of emails to fetch
            folder: Outlook folder name (inbox, sent, drafts, etc.)
            unread_only: If True, only fetch unread messages

        Returns:
            List of UnifiedMessage objects
        """
        if not self._initialized:
            if not self.initialize():
                return []

        messages = []
        outlook_folder = self._get_folder(folder)

        if not outlook_folder:
            log.warning(f"Folder not found: {folder}")
            return []

        try:
            items = outlook_folder.Items
            items.Sort("[ReceivedTime]", True)  # Sort by date descending

            count = 0
            for item in items:
                if count >= limit:
                    break

                try:
                    # Check if it's a mail item
                    if item.Class != 43:  # olMail = 43
                        continue

                    # Filter unread if requested
                    if unread_only and item.UnRead is False:
                        continue

                    # Extract message data
                    message_id = item.EntryID
                    sender = self._get_sender(item)
                    subject = item.Subject or ""
                    body = item.Body or ""
                    timestamp = self._convert_datetime(item.ReceivedTime)

                    unified_msg = UnifiedMessage(
                        id=message_id,
                        source_type="email",
                        source_adapter="outlook",
                        sender=sender,
                        subject=subject,
                        body=body,
                        timestamp=timestamp,
                        raw_metadata={
                            "folder": folder,
                            "unread": item.UnRead,
                            "importance": item.Importance,
                            "has_attachments": item.Attachments.Count > 0,
                            "attachment_count": item.Attachments.Count,
                            "attachment_names": [
                                att.FileName for att in item.Attachments
                            ] if item.Attachments.Count > 0 else [],
                            "categories": item.Categories or "",
                        }
                    )
                    messages.append(unified_msg)
                    count += 1

                except Exception as e:
                    log.warning(f"Failed to process item: {e}")
                    continue

            log.info(f"Fetched {len(messages)} emails from Outlook/{folder}")

        except Exception as e:
            log.error(f"Error fetching from Outlook: {e}")

        return messages

    def _get_sender(self, item) -> str:
        """Extract sender information from mail item."""
        try:
            if item.SenderEmailType == "EX":
                # Exchange address - get SMTP address
                try:
                    sender = item.Sender.GetExchangeUser()
                    if sender:
                        return f"{sender.Name} <{sender.PrimarySmtpAddress}>"
                except Exception:
                    pass
            return f"{item.SenderName} <{item.SenderEmailAddress}>"
        except Exception:
            return item.SenderName or "Unknown"

    def fetch_unread(self, limit: int = 10, folder: str = "inbox") -> List[UnifiedMessage]:
        """Fetch only unread emails."""
        return self.fetch(limit=limit, folder=folder, unread_only=True)

    def mark_as_read(self, message_id: str) -> bool:
        """Mark a message as read."""
        if not self._initialized:
            return False

        try:
            item = self.namespace.GetItemFromID(message_id)
            item.UnRead = False
            item.Save()
            return True
        except Exception as e:
            log.error(f"Failed to mark message as read: {e}")
            return False

    def get_attachments(self, message_id: str, output_dir: Path) -> List[Path]:
        """
        Save attachments from a message.

        Args:
            message_id: The message EntryID
            output_dir: Directory to save attachments

        Returns:
            List of saved attachment paths
        """
        if not self._initialized:
            return []

        saved = []
        output_dir.mkdir(parents=True, exist_ok=True)

        try:
            item = self.namespace.GetItemFromID(message_id)

            for attachment in item.Attachments:
                try:
                    filepath = output_dir / attachment.FileName
                    attachment.SaveAsFile(str(filepath))
                    saved.append(filepath)
                    log.info(f"Saved attachment: {filepath.name}")
                except Exception as e:
                    log.warning(f"Failed to save attachment: {e}")

        except Exception as e:
            log.error(f"Failed to get attachments: {e}")

        return saved

    # ── 이메일 검색 ──────────────────────────────────────────────

    def search_emails(
        self,
        sender: Optional[str] = None,
        subject: Optional[str] = None,
        keyword: Optional[str] = None,
        folder: str = "inbox",
        limit: int = 5,
        days_back: int = 7,
        has_attachments: bool = False,
    ) -> List[UnifiedMessage]:
        """Search emails using Outlook Restrict() DASL filters.

        Args:
            sender: Partial sender name or email to filter
            subject: Partial subject text to filter
            keyword: Keyword to search in subject + body
            folder: Outlook folder name
            limit: Maximum results
            days_back: Only search emails within this many days
            has_attachments: If True, only return emails with attachments

        Returns:
            List of matching UnifiedMessage objects
        """
        if not self._initialized:
            if not self.initialize():
                return []

        outlook_folder = self._get_folder(folder)
        if not outlook_folder:
            log.warning(f"Folder not found: {folder}")
            return []

        try:
            items = outlook_folder.Items
            items.Sort("[ReceivedTime]", True)

            # Build DASL restriction filter
            filters = []
            cutoff = datetime.now() - timedelta(days=days_back)
            cutoff_str = cutoff.strftime("%m/%d/%Y %H:%M %p")
            filters.append(f"[ReceivedTime] >= '{cutoff_str}'")

            if sender:
                filters.append(
                    f"@SQL=\"urn:schemas:httpmail:fromemail\" LIKE '%{sender}%'"
                    f" OR \"urn:schemas:httpmail:fromname\" LIKE '%{sender}%'"
                )
            if subject:
                filters.append(
                    f"@SQL=\"urn:schemas:httpmail:subject\" LIKE '%{subject}%'"
                )

            # Apply date restriction first (always safe)
            restricted = items.Restrict(filters[0])

            messages: List[UnifiedMessage] = []
            count = 0

            for item in restricted:
                if count >= limit:
                    break
                try:
                    if item.Class != 43:
                        continue

                    # Post-filter: sender
                    if sender:
                        item_sender = self._get_sender(item).lower()
                        if sender.lower() not in item_sender:
                            continue

                    # Post-filter: subject
                    if subject:
                        item_subject = (item.Subject or "").lower()
                        if subject.lower() not in item_subject:
                            continue

                    # Post-filter: keyword (subject + body)
                    if keyword:
                        combined_text = (
                            (item.Subject or "") + " " + (item.Body or "")
                        ).lower()
                        if keyword.lower() not in combined_text:
                            continue

                    # Post-filter: attachments
                    if has_attachments and item.Attachments.Count == 0:
                        continue

                    unified_msg = UnifiedMessage(
                        id=item.EntryID,
                        source_type="email",
                        source_adapter="outlook",
                        sender=self._get_sender(item),
                        subject=item.Subject or "",
                        body=item.Body or "",
                        timestamp=self._convert_datetime(item.ReceivedTime),
                        raw_metadata={
                            "folder": folder,
                            "unread": item.UnRead,
                            "importance": item.Importance,
                            "has_attachments": item.Attachments.Count > 0,
                            "attachment_count": item.Attachments.Count,
                            "attachment_names": [
                                att.FileName for att in item.Attachments
                            ] if item.Attachments.Count > 0 else [],
                            "categories": item.Categories or "",
                        },
                    )
                    messages.append(unified_msg)
                    count += 1

                except Exception as e:
                    log.warning(f"search_emails: failed to process item: {e}")
                    continue

            log.info(f"search_emails: found {len(messages)} emails")
            return messages

        except Exception as e:
            log.error(f"search_emails error: {e}")
            return []

    # ── 이메일 발송 ──────────────────────────────────────────────

    def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        cc: Optional[str] = None,
        attachments: Optional[List[str]] = None,
        html_body: bool = False,
    ) -> Dict:
        """Send a new email via Outlook COM.

        Args:
            to: Recipient email address(es), semicolon-separated
            subject: Email subject line
            body: Email body text
            cc: CC recipient(s), semicolon-separated
            attachments: List of file paths to attach
            html_body: If True, set body as HTML

        Returns:
            dict with success status and details
        """
        if not self._initialized:
            if not self.initialize():
                return {"success": False, "error": "Outlook not initialized"}

        try:
            mail = self.outlook.CreateItem(0)  # olMailItem = 0
            mail.To = to
            mail.Subject = subject

            if html_body:
                mail.HTMLBody = body
            else:
                mail.Body = body

            if cc:
                mail.CC = cc

            if attachments:
                for fpath in attachments:
                    p = Path(fpath)
                    if p.exists():
                        mail.Attachments.Add(str(p.resolve()))
                    else:
                        log.warning(f"send_email: attachment not found: {fpath}")

            mail.Send()
            log.info(f"send_email: sent to {to} — {subject}")

            return {
                "success": True,
                "to": to,
                "cc": cc or "",
                "subject": subject,
                "attachment_count": len(attachments) if attachments else 0,
            }

        except Exception as e:
            log.error(f"send_email error: {e}")
            return {"success": False, "error": str(e)}

    # ── 이메일 회신 ──────────────────────────────────────────────

    def reply_email(
        self,
        message_id: str,
        body: str,
        reply_all: bool = False,
        attachments: Optional[List[str]] = None,
    ) -> Dict:
        """Reply to an existing email via Outlook COM.

        Args:
            message_id: EntryID of the original message
            body: Reply body text (prepended to original)
            reply_all: If True, use ReplyAll instead of Reply
            attachments: List of file paths to attach

        Returns:
            dict with success status and details
        """
        if not self._initialized:
            if not self.initialize():
                return {"success": False, "error": "Outlook not initialized"}

        try:
            item = self.namespace.GetItemFromID(message_id)

            if reply_all:
                reply = item.ReplyAll()
            else:
                reply = item.Reply()

            # Prepend new body before original quoted text
            reply.Body = body + "\n\n" + reply.Body

            if attachments:
                for fpath in attachments:
                    p = Path(fpath)
                    if p.exists():
                        reply.Attachments.Add(str(p.resolve()))
                    else:
                        log.warning(f"reply_email: attachment not found: {fpath}")

            reply.Send()

            to_addr = reply.To or ""
            subj = reply.Subject or ""
            log.info(f"reply_email: replied to {to_addr} — {subj}")

            return {
                "success": True,
                "to": to_addr,
                "subject": subj,
                "reply_all": reply_all,
                "attachment_count": len(attachments) if attachments else 0,
            }

        except Exception as e:
            log.error(f"reply_email error: {e}")
            return {"success": False, "error": str(e)}

    # ── 캘린더 ───────────────────────────────────────────────────

    def get_calendar_items(self, days_ahead: int = 7) -> List[dict]:
        """
        Get upcoming calendar items.

        Args:
            days_ahead: Number of days to look ahead

        Returns:
            List of calendar item dicts
        """
        if not self._initialized:
            return []

        items = []
        try:
            calendar = self.namespace.GetDefaultFolder(9)  # olFolderCalendar

            now = datetime.now()
            end_date = datetime(
                now.year, now.month, now.day + days_ahead
            )

            restriction = f"[Start] >= '{now.strftime('%m/%d/%Y')}' AND [Start] <= '{end_date.strftime('%m/%d/%Y')}'"

            appointments = calendar.Items
            appointments.Sort("[Start]")
            appointments.IncludeRecurrences = True

            restricted = appointments.Restrict(restriction)

            for appt in restricted:
                try:
                    items.append({
                        "subject": appt.Subject,
                        "start": self._convert_datetime(appt.Start),
                        "end": self._convert_datetime(appt.End),
                        "location": appt.Location or "",
                        "organizer": appt.Organizer or "",
                    })
                except Exception:
                    continue

        except Exception as e:
            log.error(f"Failed to get calendar items: {e}")

        return items

    def close(self):
        """Clean up COM objects and uninitialize COM if we initialized it."""
        self._folders.clear()
        self.namespace = None
        self.outlook = None
        self._initialized = False

        if getattr(self, '_com_initialized', False):
            try:
                import pythoncom
                pythoncom.CoUninitialize()
            except Exception:
                pass
            self._com_initialized = False

        log.info("Outlook COM adapter closed")


# Convenience function
def fetch_outlook_emails(limit: int = 10, output_dir: Optional[Path] = None):
    """
    Fetch emails from local Outlook and save to markdown.

    Args:
        limit: Number of emails to fetch
        output_dir: Directory to save markdown files
    """
    if output_dir is None:
        output_dir = Path(__file__).parent.parent.parent / "ResearchVault/00-Inbox/Emails"

    output_dir.mkdir(parents=True, exist_ok=True)

    with OutlookAdapter() as adapter:
        messages = adapter.fetch(limit=limit)
        for msg in messages:
            filepath = adapter.save_message(msg, output_dir)
            print(f"Saved: {filepath.name}")

    return len(messages)


if __name__ == "__main__":
    # Quick test
    logging.basicConfig(level=logging.INFO)
    fetch_outlook_emails(limit=3)
