"""
Outlook COM Adapter for Local Email Collection
Uses pywin32 COM interface to access local Outlook installation.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional

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
