"""
Base classes for message adapters.
Provides unified interface for collecting messages from various sources.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional, Any
from datetime import datetime
from pathlib import Path

import yaml


@dataclass
class UnifiedMessage:
    """Unified message representation across all sources."""

    id: str
    source_type: str        # email, chat
    source_adapter: str     # imap, outlook, kakao
    sender: str
    subject: Optional[str]
    body: str
    timestamp: datetime
    raw_metadata: dict = field(default_factory=dict)

    def to_frontmatter(self) -> dict:
        """Convert to YAML frontmatter dict."""
        return {
            "type": "message",
            "source_type": self.source_type,
            "source_adapter": self.source_adapter,
            "id": self.id,
            "date": self.timestamp.strftime("%Y-%m-%d"),
            "timestamp": self.timestamp.isoformat(),
            "sender": self.sender,
            "subject": self.subject or "",
            "status": "inbox",
            "tags": [f"message/{self.source_type}"],
            "imported_at": datetime.now().isoformat(),
        }


class MessageAdapter(ABC):
    """Abstract base class for message source adapters."""

    # Class-level configuration
    adapter_name: str = "base"
    source_type: str = "unknown"
    supports_watch: bool = False
    poll_interval: int = 10  # minutes

    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}
        self._initialized = False

    @abstractmethod
    def initialize(self) -> bool:
        """
        Initialize the adapter (connect, authenticate, etc.).
        Returns True if successful.
        """
        pass

    @abstractmethod
    def fetch(self, limit: int = 10, **kwargs) -> List[UnifiedMessage]:
        """
        Fetch messages from the source.

        Args:
            limit: Maximum number of messages to fetch
            **kwargs: Adapter-specific options

        Returns:
            List of UnifiedMessage objects
        """
        pass

    def to_markdown(self, msg: UnifiedMessage, include_frontmatter: bool = True) -> str:
        """
        Convert a UnifiedMessage to Markdown format.

        Args:
            msg: The message to convert
            include_frontmatter: Whether to include YAML frontmatter

        Returns:
            Markdown string
        """
        lines = []

        if include_frontmatter:
            lines.append("---")
            fm = msg.to_frontmatter()
            lines.append(yaml.dump(fm, allow_unicode=True, default_flow_style=False).rstrip())
            lines.append("---")
            lines.append("")

        # Title
        title = msg.subject or f"Message from {msg.sender}"
        lines.append(f"# {title}")
        lines.append("")

        # Metadata
        if msg.source_type == "email":
            lines.append(f"**From:** {msg.sender}")
            lines.append(f"**Date:** {msg.timestamp.strftime('%Y-%m-%d %H:%M')}")
            lines.append("")
            lines.append("---")
            lines.append("")
        elif msg.source_type == "chat":
            lines.append(f"**Sender:** {msg.sender}")
            lines.append(f"**Time:** {msg.timestamp.strftime('%Y-%m-%d %H:%M')}")
            lines.append("")

        # Body
        lines.append(msg.body)

        return "\n".join(lines)

    def save_message(self, msg: UnifiedMessage, output_dir: Path) -> Path:
        """
        Save a message to a Markdown file.

        Args:
            msg: The message to save
            output_dir: Directory to save the file

        Returns:
            Path to the saved file
        """
        import re

        output_dir.mkdir(parents=True, exist_ok=True)

        # Generate filename
        date_str = msg.timestamp.strftime("%Y%m%d")
        subject_slug = msg.subject or "message"
        subject_slug = re.sub(r'[\\/*?:"<>|]', "", subject_slug)[:40].strip()
        subject_slug = re.sub(r'\s+', '_', subject_slug)

        filename = f"{date_str}_{self.adapter_name}_{subject_slug}.md"
        filepath = output_dir / filename

        # Handle duplicates
        counter = 1
        while filepath.exists():
            filename = f"{date_str}_{self.adapter_name}_{subject_slug}_{counter}.md"
            filepath = output_dir / filename
            counter += 1

        content = self.to_markdown(msg)
        filepath.write_text(content, encoding="utf-8")

        return filepath

    def close(self):
        """Clean up resources. Override in subclasses if needed."""
        pass

    def __enter__(self):
        self.initialize()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def get_status(self) -> dict:
        """Return adapter status information."""
        return {
            "adapter": self.adapter_name,
            "source_type": self.source_type,
            "supports_watch": self.supports_watch,
            "poll_interval": self.poll_interval,
            "initialized": self._initialized,
        }
