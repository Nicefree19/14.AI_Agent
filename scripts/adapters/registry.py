"""
Adapter Registry
Manages registration and retrieval of message adapters.
"""

from typing import Dict, List, Optional, Type
from pathlib import Path
import logging

from .base import MessageAdapter

log = logging.getLogger(__name__)

# Global adapter registry
_adapters: Dict[str, Type[MessageAdapter]] = {}
_instances: Dict[str, MessageAdapter] = {}


def register_adapter(name: str, adapter_class: Type[MessageAdapter]):
    """
    Register an adapter class.

    Args:
        name: Unique identifier for the adapter
        adapter_class: The adapter class to register
    """
    _adapters[name] = adapter_class
    log.debug(f"Registered adapter: {name}")


def get_adapter(name: str, config: Optional[dict] = None) -> Optional[MessageAdapter]:
    """
    Get an adapter instance by name.

    Args:
        name: Adapter name
        config: Optional configuration dict

    Returns:
        Adapter instance or None if not found
    """
    if name in _instances:
        return _instances[name]

    if name not in _adapters:
        log.warning(f"Adapter not found: {name}")
        return None

    try:
        instance = _adapters[name](config)
        # Call initialize() if the adapter defines it
        if hasattr(instance, "initialize") and callable(instance.initialize):
            if not instance.initialize():
                log.warning(f"Adapter '{name}' initialization returned False")
                return None
        _instances[name] = instance
        return instance
    except Exception as e:
        log.error(f"Failed to create adapter '{name}': {e}")
        return None


def get_all_adapters(config: Optional[dict] = None) -> List[MessageAdapter]:
    """
    Get instances of all registered adapters.

    Args:
        config: Optional configuration dict for all adapters

    Returns:
        List of adapter instances
    """
    adapters = []
    for name in _adapters:
        adapter = get_adapter(name, config)
        if adapter:
            adapters.append(adapter)
    return adapters


def list_adapters() -> List[str]:
    """Return list of registered adapter names."""
    return list(_adapters.keys())


def clear_instances():
    """Clear all adapter instances (for testing/reset)."""
    for instance in _instances.values():
        try:
            instance.close()
        except Exception:
            pass
    _instances.clear()


# Auto-registration of built-in adapters
def _auto_register():
    """Automatically register available adapters."""
    # IMAP adapter
    try:
        from .imap_adapter import IMAPAdapter

        register_adapter("imap", IMAPAdapter)
    except ImportError as e:
        log.debug(f"IMAP adapter not available: {e}")

    # Outlook adapter (Windows only)
    try:
        from .outlook_adapter import OutlookAdapter

        register_adapter("outlook", OutlookAdapter)
    except ImportError as e:
        log.debug(f"Outlook adapter not available: {e}")

    # KakaoTalk adapter
    try:
        from .kakao_adapter import KakaoAdapter

        register_adapter("kakao", KakaoAdapter)
    except ImportError as e:
        log.debug(f"Kakao adapter not available: {e}")

    # Telegram adapter (Layer A — passive JSON reader)
    try:
        from .telegram_adapter import TelegramAdapter

        register_adapter("telegram", TelegramAdapter)
    except ImportError as e:
        log.debug(f"Telegram adapter not available: {e}")


# Run auto-registration on module import
_auto_register()
