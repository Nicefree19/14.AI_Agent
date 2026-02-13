"""
Message Adapters Package
Unified message collection from various sources (IMAP, Outlook COM, KakaoTalk, etc.)
"""

from .base import MessageAdapter, UnifiedMessage
from .registry import get_adapter, get_all_adapters, register_adapter, list_adapters

__all__ = [
    "MessageAdapter",
    "UnifiedMessage",
    "get_adapter",
    "get_all_adapters",
    "register_adapter",
    "list_adapters",
]
