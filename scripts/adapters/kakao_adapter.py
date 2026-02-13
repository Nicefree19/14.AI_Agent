"""
KakaoTalk Adapter for Chat Message Import
Parses KakaoTalk PC export files and converts to unified message format.
"""

import re
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict

from .base import MessageAdapter, UnifiedMessage

log = logging.getLogger(__name__)


class KakaoAdapter(MessageAdapter):
    """KakaoTalk chat export adapter."""

    adapter_name = "kakao"
    source_type = "chat"
    supports_watch = False  # Manual import only
    poll_interval = 0  # Not applicable

    def __init__(self, config: Optional[dict] = None):
        super().__init__(config)
        self._current_file: Optional[Path] = None
        self._chat_name: str = ""

    def initialize(self) -> bool:
        """No initialization needed for file-based import."""
        self._initialized = True
        return True

    def set_import_file(self, filepath: Path, chat_name: Optional[str] = None):
        """
        Set the file to import.

        Args:
            filepath: Path to KakaoTalk export file
            chat_name: Optional name for the chat (defaults to filename)
        """
        self._current_file = Path(filepath)
        self._chat_name = chat_name or self._current_file.stem

    def _parse_korean_date(self, date_str: str) -> Optional[datetime]:
        """Parse Korean date format (2024년 2월 4일 ...)."""
        try:
            # Extract date parts
            match = re.match(r'(\d{4})년 (\d{1,2})월 (\d{1,2})일', date_str)
            if match:
                year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
                return datetime(year, month, day)
        except Exception:
            pass
        return None

    def _parse_time(self, time_str: str, base_date: datetime) -> datetime:
        """Parse time string and combine with base date."""
        try:
            # Handle Korean AM/PM format (오전/오후)
            time_str = time_str.strip()

            # AM/PM in Korean
            is_pm = "오후" in time_str or "PM" in time_str.upper()
            time_str = re.sub(r'(오전|오후|AM|PM)\s*', '', time_str, flags=re.IGNORECASE)

            # Parse time
            match = re.match(r'(\d{1,2}):(\d{2})', time_str)
            if match:
                hour = int(match.group(1))
                minute = int(match.group(2))

                # Convert to 24-hour format
                if is_pm and hour < 12:
                    hour += 12
                elif not is_pm and hour == 12:
                    hour = 0

                return base_date.replace(hour=hour, minute=minute, second=0)

        except Exception:
            pass

        return base_date

    def _parse_pc_format(self, content: str) -> List[Dict]:
        """
        Parse KakaoTalk PC export format.

        Format:
            --------------- 2024년 2월 4일 일요일 ---------------
            [Name] [오전 10:30] Message text

        Returns:
            List of parsed message dicts
        """
        messages = []
        lines = content.splitlines()

        current_date = datetime.now()
        date_pattern = re.compile(r'-+ (\d{4}년 \d{1,2}월 \d{1,2}일.*?) -+')
        msg_pattern = re.compile(r'\[(.*?)\] \[(.*?)\] (.*)')

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Check for date line
            date_match = date_pattern.search(line)
            if date_match:
                parsed = self._parse_korean_date(date_match.group(1))
                if parsed:
                    current_date = parsed
                continue

            # Check for message line
            msg_match = msg_pattern.match(line)
            if msg_match:
                name, time_str, text = msg_match.groups()
                timestamp = self._parse_time(time_str, current_date)

                messages.append({
                    "sender": name,
                    "timestamp": timestamp,
                    "text": text,
                    "raw_time": time_str,
                })

        return messages

    def _parse_mobile_format(self, content: str) -> List[Dict]:
        """
        Parse KakaoTalk mobile export format.

        Format varies but commonly:
            2024. 2. 4. 오전 10:30, Name : Message

        Returns:
            List of parsed message dicts
        """
        messages = []
        lines = content.splitlines()

        # Mobile format pattern
        pattern = re.compile(
            r'(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.\s*(오전|오후)?\s*(\d{1,2}):(\d{2}),\s*(.*?)\s*:\s*(.*)'
        )

        for line in lines:
            line = line.strip()
            if not line:
                continue

            match = pattern.match(line)
            if match:
                year = int(match.group(1))
                month = int(match.group(2))
                day = int(match.group(3))
                ampm = match.group(4) or ""
                hour = int(match.group(5))
                minute = int(match.group(6))
                name = match.group(7)
                text = match.group(8)

                # Adjust for AM/PM
                if "오후" in ampm and hour < 12:
                    hour += 12
                elif "오전" in ampm and hour == 12:
                    hour = 0

                timestamp = datetime(year, month, day, hour, minute)

                messages.append({
                    "sender": name,
                    "timestamp": timestamp,
                    "text": text,
                    "raw_time": f"{ampm} {hour}:{minute:02d}",
                })

        return messages

    def fetch(self, limit: int = 0, **kwargs) -> List[UnifiedMessage]:
        """
        Parse and fetch messages from the import file.

        Args:
            limit: Maximum number of messages (0 = all)
            **kwargs: Additional options
                - filepath: Override current file
                - chat_name: Override chat name

        Returns:
            List of UnifiedMessage objects
        """
        if not self._initialized:
            self.initialize()

        filepath = kwargs.get("filepath") or self._current_file
        chat_name = kwargs.get("chat_name") or self._chat_name

        if not filepath:
            log.error("No import file specified. Use set_import_file() or pass filepath kwarg.")
            return []

        filepath = Path(filepath)
        if not filepath.exists():
            log.error(f"File not found: {filepath}")
            return []

        try:
            content = filepath.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # Try alternative encodings
            for encoding in ["cp949", "euc-kr", "utf-16"]:
                try:
                    content = filepath.read_text(encoding=encoding)
                    break
                except Exception:
                    continue
            else:
                log.error(f"Failed to read file with any encoding: {filepath}")
                return []

        # Detect format and parse
        parsed = self._parse_pc_format(content)
        if not parsed:
            parsed = self._parse_mobile_format(content)

        if not parsed:
            log.warning(f"No messages parsed from {filepath}")
            return []

        # Convert to UnifiedMessage
        messages = []
        for idx, msg in enumerate(parsed):
            if limit > 0 and idx >= limit:
                break

            unified_msg = UnifiedMessage(
                id=f"{chat_name}_{msg['timestamp'].isoformat()}_{idx}",
                source_type="chat",
                source_adapter="kakao",
                sender=msg["sender"],
                subject=f"Chat: {chat_name}",
                body=msg["text"],
                timestamp=msg["timestamp"],
                raw_metadata={
                    "chat_name": chat_name,
                    "raw_time": msg.get("raw_time", ""),
                    "source_file": str(filepath),
                }
            )
            messages.append(unified_msg)

        log.info(f"Parsed {len(messages)} messages from {filepath.name}")
        return messages

    def to_markdown(self, msg: UnifiedMessage, include_frontmatter: bool = True) -> str:
        """Override to provide chat-specific formatting."""
        # For single messages in daily digest, use simpler format
        if not include_frontmatter:
            return f"- **{msg.sender}** ({msg.timestamp.strftime('%H:%M')}): {msg.body}"

        # For full message export
        return super().to_markdown(msg, include_frontmatter)

    def save_as_daily_digest(
        self,
        messages: List[UnifiedMessage],
        output_dir: Path,
        chat_name: Optional[str] = None
    ) -> List[Path]:
        """
        Save messages as daily digest files (one file per day).

        Args:
            messages: List of messages to save
            output_dir: Output directory
            chat_name: Chat name for the files

        Returns:
            List of saved file paths
        """
        import yaml

        output_dir.mkdir(parents=True, exist_ok=True)
        chat_name = chat_name or self._chat_name or "Chat"

        # Group by date
        grouped: Dict[str, List[UnifiedMessage]] = {}
        for msg in messages:
            date_key = msg.timestamp.strftime("%Y-%m-%d")
            if date_key not in grouped:
                grouped[date_key] = []
            grouped[date_key].append(msg)

        saved_files = []
        for date_str, day_messages in grouped.items():
            # Sort by timestamp
            day_messages.sort(key=lambda m: m.timestamp)

            # Clean chat name for filename
            clean_name = re.sub(r'[\\/:*?"<>|]', '', chat_name)[:30]
            filename = f"{date_str}_{clean_name}.md"
            filepath = output_dir / filename

            # Build frontmatter
            frontmatter = {
                "type": "message-log",
                "source_type": "chat",
                "source_adapter": "kakao",
                "date": date_str,
                "chat_name": chat_name,
                "message_count": len(day_messages),
                "tags": ["message/kakao"],
                "imported_at": datetime.now().isoformat(),
            }

            lines = ["---"]
            lines.append(yaml.dump(frontmatter, allow_unicode=True, default_flow_style=False).rstrip())
            lines.append("---")
            lines.append("")
            lines.append(f"# Chat Log: {chat_name} ({date_str})")
            lines.append("")

            # Add messages
            for msg in day_messages:
                time_str = msg.timestamp.strftime("%H:%M")
                lines.append(f"- **{msg.sender}** ({time_str}): {msg.body}")

            lines.append("")

            filepath.write_text("\n".join(lines), encoding="utf-8")
            saved_files.append(filepath)
            log.info(f"Saved: {filepath.name} ({len(day_messages)} messages)")

        return saved_files

    def close(self):
        """Clean up."""
        self._current_file = None
        self._chat_name = ""
        self._initialized = False


# Convenience functions for backward compatibility
def parse_kakao_pc(file_path: str) -> List[dict]:
    """Legacy function for parsing KakaoTalk PC exports."""
    adapter = KakaoAdapter()
    adapter.initialize()
    messages = adapter.fetch(filepath=file_path)

    # Convert to legacy format
    return [
        {
            "date": msg.timestamp.strftime("%Y년 %m월 %d일"),
            "name": msg.sender,
            "time": msg.raw_metadata.get("raw_time", ""),
            "text": msg.body,
        }
        for msg in messages
    ]


def save_as_markdown(messages: List[dict], source_name: str, output_dir: Optional[Path] = None):
    """Legacy function for saving parsed messages."""
    if output_dir is None:
        output_dir = Path(__file__).parent.parent.parent / "ResearchVault/00-Inbox/Messages"

    output_dir.mkdir(parents=True, exist_ok=True)

    adapter = KakaoAdapter()
    adapter._chat_name = source_name

    # Convert legacy format to UnifiedMessage
    unified = []
    for idx, msg in enumerate(messages):
        # Parse Korean date
        try:
            parts = msg["date"].replace("년 ", "-").replace("월 ", "-").replace("일", "")
            dt = datetime.strptime(parts, "%Y-%m-%d")
        except Exception:
            dt = datetime.now()

        unified.append(UnifiedMessage(
            id=f"{source_name}_{dt.isoformat()}_{idx}",
            source_type="chat",
            source_adapter="kakao",
            sender=msg["name"],
            subject=f"Chat: {source_name}",
            body=msg["text"],
            timestamp=dt,
            raw_metadata={"raw_time": msg.get("time", "")},
        ))

    adapter.save_as_daily_digest(unified, output_dir, source_name)


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) < 2:
        print("Usage: python kakao_adapter.py <kakaotalk_export.txt>")
        sys.exit(1)

    input_file = sys.argv[1]
    output_dir = Path(__file__).parent.parent.parent / "ResearchVault/00-Inbox/Messages"
    output_dir.mkdir(parents=True, exist_ok=True)

    adapter = KakaoAdapter()
    adapter.set_import_file(input_file)
    messages = adapter.fetch()

    if messages:
        saved = adapter.save_as_daily_digest(messages, output_dir)
        print(f"Saved {len(saved)} daily digest files")
    else:
        print("No messages found")
